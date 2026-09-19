# TASK-3504: Expose hash-verified definition and reference tools

**Feature**: FEAT-580 - SDD LSP Research Pilot
**Spec**: `sdd/specs/sdd-research-lsp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3500, TASK-3503
**Assigned-to**: unassigned

## Context

Implement M3 of the approved specification: expose hash-verified definition and reference tools. The reported 13% cost, 12% token and 24% call reductions are hypotheses; only the specified evaluation can establish local benefit. Read the complete spec's contracts, acceptance criteria and relevant module before implementation.

## Scope

- Create LSPToolkit(config, **kwargs), auto_open=False and tool_prefix=''; add only the two fully implemented navigation methods at this stage.
- Validate tool inputs and environment sentinel before process startup; own operation lock, lazy startup, 120-second idle shutdown and 90-second total call deadline.
- Capture before/after manifests, restart sessions on any workspace/config digest change, discard responses if the workspace changes during a call and bind permanently to one root.
- Normalize Location/LocationLink to bounded confined ranges/hashes, convert UTF-16, deduplicate and enforce limit/byte caps with omission counts and partial status.
- Map expected failures into LSPResult and propagate cancellation after cleanup; fallback text recommends wiki/AST without auto-invoking other tools.

**NOT in scope**: Diagnostic public methods/baselines (next task), wiki/MCP registration and LLM routing.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/lsp/toolkit.py` | CREATE | Task implementation |
| `packages/ai-parrot-tools/tests/lsp/test_navigation.py` | CREATE | Acceptance and regression tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

- `from parrot.tools.toolkit import AbstractToolkit` — verified in `packages/ai-parrot/src/parrot/tools/toolkit.py`; use only where relevant.

### Existing Signatures to Use

- `AbstractToolkit` — `packages/ai-parrot/src/parrot/tools/toolkit.py:206`: base toolkit, tool_prefix defaults to None; use an empty prefix for the four approved names.
- `AbstractToolkit.__init__` — `packages/ai-parrot/src/parrot/tools/toolkit.py:321`: __init__(self, **kwargs); initializes logger, _opened and _open_lock.
- `AbstractToolkit._open` — `packages/ai-parrot/src/parrot/tools/toolkit.py:390`: async _open(self) -> None; custom partial startup must clean itself up.
- `AbstractToolkit._close` — `packages/ai-parrot/src/parrot/tools/toolkit.py:406`: async _close(self) -> None; reset _opened via the superclass.
- `AbstractToolkit._ensure_open` — `packages/ai-parrot/src/parrot/tools/toolkit.py:419`: async _ensure_open(self) -> None; guarded by _open_lock.
- `AbstractToolkit.get_tools` — `packages/ai-parrot/src/parrot/tools/toolkit.py:486`: get_tools(self, permission_context=None, resolver=None) -> list[AbstractTool]; discovery must not start a process.
- `ToolkitTool._execute` — `packages/ai-parrot/src/parrot/tools/toolkit.py:145`: async _execute(self, **kwargs) -> Any; auto_open is applied before calling the bound method. Keep LSP auto_open=False.

### Dependency-produced contracts

- TASK-3500 supplies `packages/ai-parrot-tools/src/parrot_tools/lsp/snapshot.py`. Read its completed implementation and tests before consuming its API; these are planned deliverables, not verified existing symbols.
- TASK-3503 supplies `packages/ai-parrot-tools/src/parrot_tools/lsp/session.py`. Read its completed implementation and tests before consuming its API; these are planned deliverables, not verified existing symbols.

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
      "path": "packages/ai-parrot-tools/src/parrot_tools/lsp/toolkit.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/lsp/test_navigation.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit.__init__",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit._open",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit._close",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit._ensure_open",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit.get_tools",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#ToolkitTool._execute"
  ]
}
```

## Implementation Notes

- Follow the uv workspace source layout, strict type hints and async-first resource ownership. Use stdlib and already-declared Pydantic; do not add dependencies without authorization.
- Keep changes within the target table. If implementation reveals an additional target or a conflict with project conventions, report it before expanding scope.
- May run alongside tasks outside its dependency chain with disjoint targets. Requires TASK-3500, TASK-3503 for the contracts and deliverables described below.
- Activate the main repository virtual environment when using a shell in a worktree; do not create a worktree venv. Store test output in `artifacts/logs/`.
- Format touched Python with black and run ruff for touched Python files. These supplement the file-level test contract below.

## Implementation Blueprint

The following are required interfaces or artifact contracts, not claims that the symbols already exist:

- `LSPToolkit.__init__(self, config: LSPConfig | dict[str, Any], **kwargs: Any) -> None`
- `async def lsp_definition(self, path: str, line: int, column: int, expected_sha256: str) -> LSPResult`
- `async def lsp_references(self, path: str, line: int, column: int, expected_sha256: str, include_declaration: bool = False, limit: int = 50) -> LSPResult`

1. Implement private lifecycle helpers and idempotent cleanup against the completed session/snapshot APIs.
2. Add both navigation methods with input validation, generation restart and pre/post evidence verification.
3. Test result normalization, external-path omission, capped output, concurrent callers and idle cancellation; do not expose diagnostic stubs.

Use complete implementations, with no placeholder methods or unfinished public tools. Test fixtures must be deterministic and independent of live providers unless explicitly opted in.

## Acceptance Criteria

- [ ] Create LSPToolkit(config, **kwargs), auto_open=False and tool_prefix=''; add only the two fully implemented navigation methods at this stage.
- [ ] Validate tool inputs and environment sentinel before process startup; own operation lock, lazy startup, 120-second idle shutdown and 90-second total call deadline.
- [ ] Capture before/after manifests, restart sessions on any workspace/config digest change, discard responses if the workspace changes during a call and bind permanently to one root.
- [ ] Normalize Location/LocationLink to bounded confined ranges/hashes, convert UTF-16, deduplicate and enforce limit/byte caps with omission counts and partial status.
- [ ] Map expected failures into LSPResult and propagate cancellation after cleanup; fallback text recommends wiki/AST without auto-invoking other tools.
- [ ] All target files are complete and file-level validation passes.
- [ ] No unrelated files or actual developer host configuration are changed.
- [ ] Failures, unavailable prerequisites and verification limitations are recorded honestly in the completion note.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/lsp/test_navigation.py -q`

## Test Specification

- `test_definition_reference_normalization`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_hash_mismatch_and_workspace_changed`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_no_io_on_construction_and_listing`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_lifecycle_cancel_idle_shutdown`: cover the corresponding scope invariant with both successful and adversarial inputs.

## Agent Instructions

1. Read the approved spec and this task; verify prerequisites in `sdd/tasks/index/sdd-research-lsp.json`.
2. Mark only this task in-progress with assignment/start timestamp before implementing.
3. Reverify existing and dependency-produced contracts; follow the file scope and update the task first if an approved scope correction is needed.
4. Implement and run the validation above; record actual results and any external blockers.
5. Run the required SDD review, then commit only task-scoped implementation plus this task and its per-spec index state. Do not use the historical monolithic index.
6. Mark done only when every acceptance criterion is satisfied. Leave blocked external execution unfinished.

## Completion Note

**Scope correction applied during dispatch (worth recording):** the dispatch briefing described all four
public tools; this task file's own Scope/NOT-in-scope/Implementation Blueprint/Acceptance Criteria sections
explicitly restrict it to the two navigation methods only ("add only the two fully implemented navigation
methods at this stage" / "NOT in scope: Diagnostic public methods/baselines (next task)"), with TASK-3505
depending on TASK-3504 to cover diagnostics. The implementing coder correctly followed the task file (the
authority) over the broader briefing and implemented only `lsp_definition`/`lsp_references` — flagged here so
the discrepancy is visible, not silently resolved either way.

Implemented `LSPToolkit(AbstractToolkit)` with `auto_open=False`, `tool_prefix=""`, exactly two public tools
(`lsp_definition`, `lsp_references`; private helpers underscore-prefixed so `_generate_tools()` never exposes
them). `__init__` does pure validation only, no I/O (verified by a test that makes `capture_workspace`/
`PyrightSession` raise if invoked at construction/listing time). `environment_id="operator-unconfigured"`
short-circuits to `status="unavailable", code="invalid_request"` before any snapshot/session touch.

Per-call flow: validate `SourcePosition`/`limit` bound → capture "before" `WorkspaceSnapshot` → verify
`expected_sha256` (mismatch → `source_changed`) → lazily start/restart `PyrightSession` when the workspace/config
digest changed since last (re)start → `sync_documents` → allowlisted `textDocument/definition`/`references`
request → normalize `Location`/`LocationLink`, omitting anything outside `repo_root`, non-`.py`/`.pyi`, or not
in the tracked/untracked manifest → capture "after" snapshot, discard as `workspace_changed` if the digest
moved during the call → dedupe → enforce the 200-item render cap and 32 KiB JSON cap with explicit
`truncated`/`omitted_count` → build `EvidenceMeta`/`LSPResult`. One per-instance `asyncio.Lock` serializes
calls; whole call wrapped in a 90s total-deadline `asyncio.wait_for` (timeout → `request_timeout`); external
`CancelledError` propagates untouched (verified: lock released, follow-up call still completes). 120s idle
shutdown via a self-rescheduling task closing the owned session.

**Design note for M4 (TASK-3506+):** because `auto_open=False` means the framework's `_opened`-gated `_close()`
call in the MCP factory never fires for this toolkit, `cleanup()` is overridden to `await self._close()` so
shutdown always actually happens. This follows from reading `toolkit_server.py`'s `_opened` gate directly and
is not in the task's own text — flagged for whoever wires this toolkit's lifecycle against TASK-3506's owned
MCP server wrapper (already merged; worth a compatibility check but not re-opened here since M4 predates M3 in
delivery order and its own tests already cover "no-resource toolkits").

`LSPFailure` → `LSPResult` mapping: `server_missing`/`server_version_mismatch`/`startup_timeout`/`server_crashed`
→ `status="unavailable"`; everything else → `status="error"`. Every failure/unavailable result carries a fixed
fallback string recommending wiki/AST/source or tests/lint, never auto-invoking another tool.

**Codebase Contract check (requested by TASK-3499):** `DiagnosticBatch`/`DiagnosticSnapshot.diagnostics:
dict[str, list[RawDiagnostic]]` is diagnostics-only; this task (navigation only) never touches it — no fit
problem to report, out of this task's scope.

No live Pyright executable was available in this sandboxed environment; all toolkit-level tests substitute a
deterministic `FakeSession` double for `PyrightSession` (consistent with M2's own "real subprocess for
lifecycle, synthetic messages for content" convention) — real end-to-end Pyright behavior remains covered only
by TASK-3508's pinned-Pyright integration tests.

Validation: `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src pytest
packages/ai-parrot-tools/tests/lsp/test_navigation.py -q` → 12 passed. Full `packages/ai-parrot-tools/tests/lsp/`
(89 tests) → all passed, no regression. `black`/`ruff check` clean on both files.

Post-merge regression (`select_tests --tier merge`): 98 passed (`dev_loop/sdd_coder` + `packages/ai-parrot/tests/mcp`),
119 passed/1 deselected (`packages/ai-parrot-tools/tests/lsp` + `tool_optimizations/integration`), 15 passed
(`tests/mcp/test_toolkit_server.py`).

Coder-feedback patterns checked: hasattr-duck-typing — not applicable (`isinstance` checks ordered
specific-to-general: `LocationLink`'s `targetUri` before falling back to `Location`'s `uri`).
unisolated-real-home-in-tests — not applicable (all I/O confined to `tmp_path`-based git repos).
unscoped-removal-reuses-full-uninstall-helper — not applicable (`_close()`/`_close_session_locked()` are new,
narrowly-scoped helpers; `PyrightSession.close()`'s documented idempotent contract was read in full before
calling it).

No code review deferred findings for this delivery; the scope correction and M4-compatibility note above are
carried forward for reviewer awareness, not defects. No correction feedback filed.

Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: n/a (not reported by native
Agent dispatch) · Tokens: 248900 (subagent_tokens, per completion notification).
