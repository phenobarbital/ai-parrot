# TASK-3505: Expose checkpoint diagnostics and bounded baseline deltas

**Feature**: FEAT-580 - SDD LSP Research Pilot
**Spec**: `sdd/specs/sdd-research-lsp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3504
**Assigned-to**: unassigned

## Context

Implement M3 of the approved specification: expose checkpoint diagnostics and bounded baseline deltas. The reported 13% cost, 12% token and 24% call reductions are hypotheses; only the specified evaluation can establish local benefit. Read the complete spec's contracts, acceptance criteria and relevant module before implementation.

## Scope

- Add lsp_diagnostics and lsp_diagnostic_delta with 1–20 saved-file scope and typed evidence.
- Retain only complete raw sets in eight-entry LRU baselines with 30-minute TTL; allow source-only generation changes but reject incompatible environment/config/server identity.
- Compare diagnostic multisets using full path/source/code/severity/message keys and counts, excluding ranges; preserve current range evidence and output caps.
- Reject mismatched scope, missing/deleted files, expired IDs and incomplete diagnostics explicitly; no empty clean status from timeout/unversioned notifications.
- Verify final tools list has exactly four methods and private helpers/lifecycle are excluded.

**NOT in scope**: Host config, automatic remediation, saved baseline persistence and live evaluation.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/lsp/toolkit.py` | MODIFY | Task implementation |
| `packages/ai-parrot-tools/tests/lsp/test_diagnostic_baselines.py` | CREATE | Acceptance and regression tests |

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

- TASK-3504 supplies `packages/ai-parrot-tools/src/parrot_tools/lsp/toolkit.py`. Read its completed implementation and tests before consuming its API; these are planned deliverables, not verified existing symbols.

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
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/lsp/test_diagnostic_baselines.py",
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
- May run alongside tasks outside its dependency chain with disjoint targets. Requires TASK-3504 for the contracts and deliverables described below.
- Activate the main repository virtual environment when using a shell in a worktree; do not create a worktree venv. Store test output in `artifacts/logs/`.
- Format touched Python with black and run ruff for touched Python files. These supplement the file-level test contract below.

## Implementation Blueprint

The following are required interfaces or artifact contracts, not claims that the symbols already exist:

- `async def lsp_diagnostics(self, paths: list[str]) -> LSPResult`
- `async def lsp_diagnostic_delta(self, baseline_id: str, paths: list[str]) -> LSPResult`

1. Extend the dependency's toolkit using its shared operation and lifecycle paths rather than creating a second session.
2. Implement complete-baseline admission, LRU/TTL and compatible multiset delta rules; never truncate the internally compared messages.
3. Test line shifts, duplicate findings, deletions, cap overflow and incompatible generations; assert four public tool schemas.

Use complete implementations, with no placeholder methods or unfinished public tools. Test fixtures must be deterministic and independent of live providers unless explicitly opted in.

## Acceptance Criteria

- [ ] Add lsp_diagnostics and lsp_diagnostic_delta with 1–20 saved-file scope and typed evidence.
- [ ] Retain only complete raw sets in eight-entry LRU baselines with 30-minute TTL; allow source-only generation changes but reject incompatible environment/config/server identity.
- [ ] Compare diagnostic multisets using full path/source/code/severity/message keys and counts, excluding ranges; preserve current range evidence and output caps.
- [ ] Reject mismatched scope, missing/deleted files, expired IDs and incomplete diagnostics explicitly; no empty clean status from timeout/unversioned notifications.
- [ ] Verify final tools list has exactly four methods and private helpers/lifecycle are excluded.
- [ ] All target files are complete and file-level validation passes.
- [ ] No unrelated files or actual developer host configuration are changed.
- [ ] Failures, unavailable prerequisites and verification limitations are recorded honestly in the completion note.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/lsp/test_diagnostic_baselines.py -q`

## Test Specification

- `test_baseline_delta_scope_and_counts`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_baseline_ttl_lru_and_config_change`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_incomplete_diagnostics_never_create_baseline`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_tool_schema_exactly_four_methods`: cover the corresponding scope invariant with both successful and adversarial inputs.

## Agent Instructions

1. Read the approved spec and this task; verify prerequisites in `sdd/tasks/index/sdd-research-lsp.json`.
2. Mark only this task in-progress with assignment/start timestamp before implementing.
3. Reverify existing and dependency-produced contracts; follow the file scope and update the task first if an approved scope correction is needed.
4. Implement and run the validation above; record actual results and any external blockers.
5. Run the required SDD review, then commit only task-scoped implementation plus this task and its per-spec index state. Do not use the historical monolithic index.
6. Mark done only when every acceptance criterion is satisfied. Leave blocked external execution unfinished.

## Completion Note

Not completed. The implementing agent must record changed behavior, validation results, commit, review outcome and remaining limitations here.
