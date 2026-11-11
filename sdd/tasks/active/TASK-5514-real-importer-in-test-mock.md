# TASK-5514: Call the real importer from the toolkit-server test import mock

**Feature**: FEAT-879 fixgroup-4ab74072d1a9
**Spec**: `sdd/specs/fixgroup-4ab74072d1a9.spec.md`
**Status**: pending
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

_(filled in on close)_
