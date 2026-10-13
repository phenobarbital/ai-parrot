# TASK-4272: Add structured logging to LSPToolkit

**Feature**: FEAT-658 — lsp-toolkit-tech-debt
**Spec**: sdd/specs/lsp-toolkit-tech-debt.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: agent

## Context

LSPToolkit (947 lines) has zero `self.logger` calls. Both `PyrightSession` and
`_ToolkitStdioMCPServer` log correctly — `LSPToolkit` is the outlier. CLAUDE.md
mandates `self.logger` over silence.

Resolves ledger issue:f00bb9ef1e72.

## Scope

Add `self.logger` calls at lifecycle and error points.

### NOT in scope
- Changing log levels in PyrightSession or other components
- Adding structured logging infrastructure beyond what AbstractToolkit provides

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/lsp/toolkit.py` | MODIFY | Add self.logger calls |
| `packages/ai-parrot-tools/tests/lsp/test_toolkit_logging.py` | CREATE | Verify log output |

## Codebase Contract

### Verified Imports
- `parrot_tools.lsp.toolkit.LSPToolkit` — class at line 133
- `parrot_tools.lsp.toolkit.LSPToolkit._open` — async method at line 247
- `parrot_tools.lsp.toolkit.LSPToolkit._close` — async method at line 251
- `parrot_tools.lsp.toolkit.LSPToolkit._close_session_locked` — async method at line 450
- `parrot_tools.lsp.toolkit.LSPToolkit._idle_shutdown` — async method at line 485
- `parrot_tools.lsp.toolkit.LSPToolkit._failure_result` — method at line 938

### Existing Signatures
- `async def _open(self) -> None` (line 247)
- `async def _close(self) -> None` (line 251)
- `async def _close_session_locked(self) -> None` (line 450)
- `async def _idle_shutdown(self, delay: float) -> None` (line 485)
- `def _failure_result(self, operation: str, exc: LSPFailure) -> LSPResult` (line 938)

### Does NOT Exist
- No `self.logger` calls exist anywhere in toolkit.py currently

## Implementation Notes

Add the following `self.logger` calls:
1. `_open()` (line ~247): `self.logger.debug("LSPToolkit session opened for %s", self._workspace_id[:8])`
2. Inside `_ensure_session_locked()` after cold start vs reuse decision: `self.logger.debug(...)` with cold_start flag
3. `_close()` / `_close_session_locked()`: `self.logger.debug("closing LSP session")`
4. `_idle_shutdown()` when timer fires: `self.logger.debug("idle shutdown after %.0fs", delay)`
5. `_failure_result()`: `self.logger.warning("LSP %s failed: [%s] %s", operation, exc.code, exc.detail)`

## Acceptance Criteria

- [ ] `grep -c 'self\.logger\.' toolkit.py` returns ≥ 4
- [ ] Existing LSP tests pass

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src pytest packages/ai-parrot-tools/tests/lsp/test_toolkit_logging.py -x -q
ruff check packages/ai-parrot-tools/src/parrot_tools/lsp/toolkit.py
```

## Completion Note

(filled by implementing agent)


Completed: implemented as specified; tests in tests/lsp (33 passed).
