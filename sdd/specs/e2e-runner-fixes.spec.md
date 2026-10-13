# E2E Runner Fixes — FEAT-660

```yaml
type: feature
base_branch: dev
projects: [ai-parrot-server]
tags: [e2e, runner, bridge, tech-debt, ledger-fix]
```

## 1. Problem

Two issues from the FEAT-581 E2E testing work:

1. **Bridge node-ID mismatch** (issue:bf98b8ae2ae7, major) — `_bridge_results()`
   in `runner.py` looks up `observed.get(node_id)` using repo-root-relative
   node IDs from the E2E plan (e.g. `packages/ai-parrot-server/tests/e2e/...`),
   but pytest runs with `packages/ai-parrot-server` as rootdir, so the bridge
   JSON records tests under package-relative keys (`tests/e2e/...`). The lookup
   never matches, producing false `node_not_collected` failures even when tests
   pass. Blocks genuine full-plan PASS today.

2. **Duplicated pass/fail logic** (issue:b8ccc87e9274, minor) — `runner.py`'s
   `_verdict_status` and `evidence.py`'s `verify_evidence` independently compute
   required-node pass/fail with no shared helper. Currently consistent but
   future edits could silently diverge.

## 2. Solution

### M1 — Normalize bridge node-ID lookup (runner.py)

In `_bridge_results`, normalize both sides (plan node_ids and bridge-observed
keys) to the same relative base before lookup. Use the pytest rootdir from the
scenario's package to strip/add the prefix consistently. This applies to both
`runner.py`'s bridge lookup and the bridge JSON writer.

### M2 — Extract shared verdict helper (runner.py + evidence.py)

Extract the "required node → pass/fail/blocked" computation into a shared
helper in a common module (e.g. `e2e/_verdict.py`) that both `runner.py` and
`evidence.py` call.

## 3. Files

| File | Module | Action |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/e2e/runner.py` | M1, M2 | MODIFY |
| `packages/ai-parrot-server/src/parrot/e2e/evidence.py` | M2 | MODIFY |
| `packages/ai-parrot-server/src/parrot/e2e/_verdict.py` | M2 | CREATE |
| `packages/ai-parrot-server/tests/e2e/test_runner_bridge.py` | M1 | CREATE |

## 4. Acceptance Criteria

- AC1: Bridge lookup matches tests regardless of rootdir prefix
- AC2: `_verdict_status` and `verify_evidence` share one helper for required-node logic
- AC3: `ruff check` passes on all modified files
- AC4: Existing e2e tests pass
