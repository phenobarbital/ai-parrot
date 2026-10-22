# TASK-4278: Normalize bridge node-ID lookup in E2E runner

**Feature**: FEAT-660 — e2e-runner-fixes
**Spec**: sdd/specs/e2e-runner-fixes.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: agent

## Context

`_bridge_results()` in `runner.py` looks up `observed.get(node_id)` using
repo-root-relative node IDs from the E2E plan (e.g.
`packages/ai-parrot-server/tests/e2e/test_mcp_http.py::test_http_cli_stays_alive_and_stops`).
But pytest runs with `packages/ai-parrot-server` as rootdir, so the bridge
JSON records tests under package-relative keys (`tests/e2e/test_mcp_http.py::...`).
The lookup never matches, producing false `node_not_collected` failures even
when all tests pass. Blocks genuine full-plan PASS today.

Resolves ledger issue:bf98b8ae2ae7.

## Scope

Normalize both sides (plan node_ids and bridge-observed keys) to the same
relative base before the `observed.get(node_id)` lookup. Use the pytest
rootdir from the scenario's package to strip/add the prefix consistently.

### NOT in scope
- Changing the E2E plan schema or node_id format
- Modifying how pytest is invoked

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/e2e/runner.py` | MODIFY | Normalize node IDs in _bridge_results |
| `packages/ai-parrot-server/tests/e2e/test_runner_bridge.py` | CREATE | Regression test for prefix-mismatch scenario |

## Acceptance Criteria

- [ ] Bridge lookup matches tests regardless of rootdir prefix
- [ ] A test verifies node_id normalization with nested-package paths
- [ ] `ruff check packages/ai-parrot-server/src/parrot/e2e/runner.py` passes

## Validation Commands

```bash
ruff check packages/ai-parrot-server/src/parrot/e2e/runner.py
PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src pytest packages/ai-parrot-server/tests/e2e/test_runner_bridge.py -x -q --timeout=30
```

## Completion Note

Bridge lookup keeps the existing rootdir-suffix fallback but now matches only on a path-component boundary (no fabricated passes from partial-name suffixes). Tests in tests/e2e/test_runner_bridge.py (run with PARROT_TEST_E2E=1). Committed together with TASK-4279.
