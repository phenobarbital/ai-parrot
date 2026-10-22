---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [lsp, pyright, ledger-fix]
---

# Feature Specification: Pyright `extraPaths` reach the server (FEAT-580 follow-up)

**Feature ID**: FEAT-630
**Date**: 2026-10-05
**Author**: agent:sdd-fix
**Status**: approved
**Target version**: next
**Origin**: `/sdd-fix` ledger group `fixgroup:950c492d7519`, `issue:f439688c6651`
(`discovered_from: spec:FEAT-580`). Parent spec: FEAT-580 (LSP pilot, completed).

---

## 1. Motivation & Business Requirements

### Problem Statement

`test_pyright_pinned_navigation` fails against a real, pinned Pyright 1.1.414: a
`textDocument/definition` on a symbol imported through a PEP 420 namespace root listed in
`LSPConfig.source_roots` returns `null`, so `ns_result.locations == []`.

Re-derived on 2026-10-05 (origin/dev @ `0fbe20fbb`) by logging the live JSON-RPC traffic:

- Pyright 1.1.414 pulls `workspace/configuration` only for the sections `python` and `pyright`.
  It **never** requests `python.analysis`. It reads analysis settings from the nested
  `analysis` key of the `python` section object.
- `PyrightSession._resolve_configuration_item("python")` answers `{"pythonPath": …}` only, and the
  `python.analysis` answer is never asked for. So `extraPaths`, `diagnosticMode` and
  `typeCheckingMode` never reach the server. The same applies to `initializationOptions`, which
  sends a flat `"python.analysis"` key.
- The Pyright CLI with an equivalent `pyrightconfig.json` `extraPaths` resolves the import, and so
  does the LSP session once `python.analysis` settings are nested under `python.analysis`.
  The workspace-folder handling of `source_roots` is not the cause, because removing those
  folders does not change the result.

The defect went unnoticed because the integration module always skipped: Pyright was never
installed in any environment until FEAT-580 TASK-3514.

### Goals
- G1: the `python` configuration section (pull and `initializationOptions`) carries the pinned
  analysis settings nested as `analysis`, so `extraPaths` derived from `source_roots` takes effect.
- G2: `test_pyright_pinned_navigation` passes against real Pyright 1.1.414.

### Non-Goals
- Workspace-folder handling of `source_roots` (unchanged).
- Dropping the flat `python.analysis` answer. It stays for clients/servers that pull it.

---

## 2. Architectural Design

`parrot_tools/lsp/session.py`: `_python_settings(config)` returns
`{"pythonPath": …, "analysis": self._python_analysis_settings(config)}`. The flat
`python.analysis` pull answer and `initializationOptions["python.analysis"]` are kept.

---

## 3. Module Breakdown
One task (TASK-4060): session settings shape + unit tests + a tighter integration assertion.

## 4. Test Specification
| Test | File | Covers |
|---|---|---|
| `TestPinnedPythonAnalysisConfiguration` (updated) | `tests/lsp/test_session_lifecycle.py` | G1 |
| `test_pyright_pinned_navigation` (exact-path assertion) | `tests/lsp/test_pyright_integration.py` | G2 |

## 5. Acceptance Criteria
- [ ] AC1: `_resolve_configuration_item({"section": "python"})["analysis"]["extraPaths"]` lists the
  `source_roots`; `initializationOptions["python"]["analysis"]` matches.
- [ ] AC2: `PARROT_LSP_REQUIRE_PYRIGHT=1 pytest packages/ai-parrot-tools/tests/lsp/test_pyright_integration.py`
  is green with pyright 1.1.414 on PATH, and the namespace definition resolves to exactly
  `packages/pkg-a/src/pkg_ns/helper.py`.
- [ ] AC3: `pytest packages/ai-parrot-tools/tests/lsp/` is green and `ruff check` is clean on the touched files.

## 6. Codebase Contract
Verified on origin/dev @ `0fbe20fbb`:
- `packages/ai-parrot-tools/src/parrot_tools/lsp/session.py`: `PyrightSession._python_settings(self, config)`,
  `_python_analysis_settings(self, config)`, `_resolve_configuration_item(self, item)`,
  `_build_initialize_params(self, config)`
- `packages/ai-parrot-tools/tests/lsp/test_session_lifecycle.py`: `class TestPinnedPythonAnalysisConfiguration`

## 7. Open Questions
None.
