---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [mcp, toolkit-server, tests, bugfix]
docs:
  policy: none
---

# Feature Specification: Stop the toolkit-server test import mock from recursing

**Feature ID**: FEAT-879
**Date**: 2026-11-11
**Author**: Jesus Lara
**Status**: approved
**Discovered-from**: `issue:203c75e0c1ac`

## 1. Problem

`issue:203c75e0c1ac`: 12 of the tests in `tests/mcp/test_toolkit_server.py` fail on `dev` with
`RecursionError` (reproduced again as baseline reds during the FEAT-877 closeout, 2026-11-11).

The tests patch `"parrot.mcp.toolkit_server.importlib.import_module"`. `toolkit_server.importlib` is the
global `importlib` module, so the patch replaces `importlib.import_module` process-wide. The test helper
`mock_import_module` returns a stub module for `stub_toolkit` names and otherwise falls back to
`importlib.import_module(name)` — which is now the helper itself. Any import of a non-stub module during
the test therefore recurses until the interpreter's recursion limit. `refusing_import` (the
"never imports the client factory" test) delegates to the same helper.

The fallback used to be unreachable. It became reachable when tool generation started resolving host
toolkit classes (`AbstractToolkit._create_tool_from_method` → `effective_access` → `_is_host_class` →
`ToolkitResolver.resolve` → `discovery.resolve_class` → `importlib.import_module`), which imports real
modules while the patch is active.

## 2. Goals

- G1: the import mock's fallback calls the real `importlib.import_module`, captured before any patch.
- G2: every test in `tests/mcp/test_toolkit_server.py` passes on `dev`.

## 3. Non-goals

- Any production code change (`parrot/mcp/toolkit_server.py`, `parrot/tools/*` stay untouched).
- Narrowing the patch target to a module-local import (the existing tests' patch target is kept).

## 4. Design

Test-only. Capture `_REAL_IMPORT_MODULE = importlib.import_module` at module import time in
`tests/mcp/test_toolkit_server.py`, and use it for every fallback import inside the test helpers
(`mock_import_module`, and any other helper that delegates to the real importer). Tests that assert a
module is *not* imported keep their assertion.

## 5. Acceptance Criteria

- AC1: `pytest tests/mcp/test_toolkit_server.py` passes with 0 failures.
- AC2: no `RecursionError` in the run; the stub toolkit is still served through the patched importer.
- AC3: no files outside `tests/mcp/test_toolkit_server.py` change.

## 6. Tasks

- TASK-5514 — call the real importer from the toolkit-server test import mock.
