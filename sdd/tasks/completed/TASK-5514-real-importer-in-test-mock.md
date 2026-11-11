# TASK-5514: Call the real importer from the toolkit-server test import mock

**Feature**: FEAT-879 fixgroup-4ab74072d1a9
**Spec**: `sdd/specs/fixgroup-4ab74072d1a9.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:203c75e0c1ac`

## Context

See spec §1. Patching `parrot.mcp.toolkit_server.importlib.import_module` replaces the global
`importlib.import_module`; the test helper's fallback `importlib.import_module(name)` then calls itself.

## Scope

- Capture the real `importlib.import_module` once at module import time.
- Route every fallback import in the test helpers through that captured function.

**NOT in scope**: production code; changing the patch target; adding or removing tests.

## Files to Modify

- `tests/mcp/test_toolkit_server.py`

## Codebase Contract

### Verified Imports / Existing Signatures

- `tests/mcp/test_toolkit_server.py`: `import importlib` (line 7); `mock_import_module(name)` (line 28,
  fallback `return importlib.import_module(name)` at line 40); `refusing_import(name, *args, **kwargs)`
  inside `test_deterministic_toolkit_never_imports_the_client_factory` (line ~309, delegates to
  `mock_import_module`); patch target `"parrot.mcp.toolkit_server.importlib.import_module"`.
- `parrot.mcp.toolkit_server`: `import importlib` (line 9); `importlib.import_module(module_name)` (line 313).

### Does NOT Exist

- A module-local `import_module` alias in `parrot.mcp.toolkit_server` (the patch hits the global function).

## Acceptance Criteria

AC1–AC3 of the spec.

## Validation Commands

- `pytest tests/mcp/test_toolkit_server.py`

Run from the worktree root with `PYTHONPATH=$PWD/packages/ai-parrot/src`; lint with
`ruff check tests/mcp/test_toolkit_server.py`.

## Completion Note

Implemented in 71db31beee. `tests/mcp/test_toolkit_server.py` captures `_REAL_IMPORT_MODULE =
importlib.import_module` at module import time, before any test patches the global function, and
`mock_import_module` falls back to it instead of the (patched) `importlib.import_module`.
`refusing_import` delegates to `mock_import_module`, so it is fixed by the same change and still
refuses `parrot.clients.factory`. No production code changed.
Validation: `pytest tests/mcp/test_toolkit_server.py` 22 passed (was 12 failed / 10 passed on base
6c51de8c38); neighbour `tests/mcp/test_local_cli.py` 13 passed; ruff + black clean.
Resolves `issue:203c75e0c1ac`.
