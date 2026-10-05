# TASK-4060: Nest python.analysis settings under the `python` section for Pyright

**Feature**: FEAT-630 (Pyright `extraPaths` reach the server)
**Spec**: `sdd/specs/lsp-test-pyright-integration-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 1h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Resolves ledger issue `issue:f439688c6651`. Pyright 1.1.414 only pulls the `python` section and
reads analysis settings from its nested `analysis` key, so `extraPaths` never reached it (spec §1).

## Scope

- `session.py`: `_python_settings` adds `"analysis": self._python_analysis_settings(config)`.
  This one change covers both the configuration pull and `initializationOptions["python"]`.
- `test_session_lifecycle.py`: update `TestPinnedPythonAnalysisConfiguration` expectations for the
  nested key. Keep the flat `python.analysis` assertions.
- `test_pyright_integration.py`: tighten the namespace assertion to the exact repo-relative path
  `packages/pkg-a/src/pkg_ns/helper.py`.

**NOT in scope**: workspace-folder handling; removing the flat `python.analysis` answer.

## Files to Create / Modify
| File | Action |
|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/lsp/session.py` | MODIFY |
| `packages/ai-parrot-tools/tests/lsp/test_session_lifecycle.py` | MODIFY |
| `packages/ai-parrot-tools/tests/lsp/test_pyright_integration.py` | MODIFY |

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# parrot_tools/lsp/session.py (class PyrightSession)
def _python_settings(self, config: LSPConfig) -> dict[str, Any]
def _python_analysis_settings(self, config: LSPConfig) -> dict[str, Any]
def _resolve_configuration_item(self, item: Any) -> Any
def _build_initialize_params(self, config: LSPConfig) -> dict[str, Any]
```

### Does NOT Exist
- No `analysis` key in the `python` section today.

## Acceptance Criteria
Spec §5 AC1–AC3.

## Validation Commands
```bash
PYTHONPATH=packages/ai-parrot-tools/src pytest packages/ai-parrot-tools/tests/lsp/ -q
PYTHONPATH=packages/ai-parrot-tools/src PARROT_LSP_REQUIRE_PYRIGHT=1 pytest packages/ai-parrot-tools/tests/lsp/test_pyright_integration.py -q
ruff check packages/ai-parrot-tools/src/parrot_tools/lsp/session.py packages/ai-parrot-tools/tests/lsp/
```

## Completion Note
**Completed**: 2026-10-05 by agent:sdd-fix, code commit `ea68e7ad9`. Verified.

- Root cause, confirmed from live JSON-RPC traffic: Pyright 1.1.414 pulls only the `python` and
  `pyright` sections and never requests `python.analysis`, so `extraPaths` was never applied.
- Fix: `_python_settings` nests `analysis` under the `python` section. This one change covers both
  the pull and `initializationOptions`. The flat `python.analysis` answer is kept.
- Validation: `tests/lsp/` 168 passed. `PARROT_LSP_REQUIRE_PYRIGHT=1` real-Pyright module 3 passed,
  run with pyright 1.1.414 on PATH (not skipped). ruff and black are clean.
- Resolves ledger `issue:f439688c6651`.
