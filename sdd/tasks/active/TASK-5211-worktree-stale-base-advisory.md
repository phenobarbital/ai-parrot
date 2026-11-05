# TASK-5211: Wire host-only stale-base advisories into startup

**Feature**: FEAT-806 — Worktree Sync Base
**Spec**: `sdd/specs/worktree-sync-base.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5207
**Assigned-to**: unassigned

## Context

M5 implements approved Q3: show base freshness on host startup without modifying the feature branch or blocking the worker.

## Scope

Call stale_base_summary after prepare_upstream only when no_upstream is false; add host-only sdd-start dry-run text and twins. Preserve python -S tmux child isolation and existing environment snapshot behavior. NOT in scope: core summary implementation, automatic sync, worker sandbox checks.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` | MODIFY | Host preparation advisory |
| `packages/ai-parrot/tests/sdd/test_sdd_launch.py` | MODIFY | Startup ordering and compatibility tests |
| `.claude/commands/sdd-start.md` | MODIFY | Host sdd-start advisory twin |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-start.md` | MODIFY | Host sdd-start advisory twin |
| `.agent/workflows/sdd-start.md` | MODIFY | Host sdd-start advisory twin |
| `packages/ai-parrot/src/parrot/sdd/_assets/agent/workflows/sdd-start.md` | MODIFY | Host sdd-start advisory twin |

## Codebase Contract (Anti-Hallucination)

Verified at `cd57902e64`. Dependency-created symbols are explicitly identified below; verify them after dependencies land.

### Verified Imports
```python
import sys
from pathlib import Path
import pytest
from parrot.flows.dev_loop import feature_launcher as launcher
```
The launcher/test imports already exist. Dependency import inside host preparation only: `from parrot.sdd.scripts.worktree_sync import stale_base_summary` (created by TASK-5207).

### Existing Signatures to Use
`packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:253`: `prepare_upstream(worktree: Path) -> str`; launch host preparation calls it at :507. `launch` already accepts no_upstream and has a separate --in-session child path. Module docstring requires stdlib-only top-level imports because child starts under python -S. Existing test at `packages/ai-parrot/tests/sdd/test_sdd_launch.py:961` verifies this guarantee. The repeated monkeypatch anchor is scoped by the two function names in the blueprint.

### Does NOT Exist
- No stale-base advisory in either entry point today.
- No worker-side full-base transport; do not add an advisory to the sandbox child.


## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_sdd_launch.py",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-start.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-start.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-start.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/_assets/agent/workflows/sdd-start.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py#launch",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py#prepare_upstream"
  ]
}
```

## Implementation Notes

Consumes TASK-5207 stale_base_summary in worktree_sync.py. No edge to TASK-5209: docs mention the CLI but launcher calls the API directly; CLI registration is verified by its own task. TASK-5210 edits different worker/rule documents.

Use repository tools from the activated environment; preserve shared environments. Keep changes within declared files, use typed functions and Google-style docstrings, black (120 columns), and ruff. Tests must import this worktree's source, not another editable checkout. No new dependency is authorized. CLI subprocess I/O is synchronous by design; do not introduce blocking I/O into async entry points. Run no network or destructive operations against the real repository in tests.

## Implementation Blueprint

Blueprint gaps below are planning instructions only; finished code must have no placeholders.

### Steps (in order)

1. Verify host and --in-session paths — the new dependency must not load in the stdlib-only child.
2. Insert advisory after successful upstream preparation — retain preflight/order and no-upstream semantics.
3. Stub the advisory in existing fake launch fixtures and add targeted order/skip tests — tests must not fetch real remotes.
4. Update all declared startup twins and run launcher plus parity checks — host-only behavior must be consistent.

### `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` (MODIFY)

Anchor `print(prepare_upstream(worktree), file=sys.stderr)` — packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:507, occurrences: 1 (verified at cd57902e64).

```python
# Keep this import inside host preparation, after prepare_upstream succeeds.
# Never add a module-level parrot/Pydantic import: the tmux child runs python -S.
if not no_upstream:
    print(prepare_upstream(worktree), file=sys.stderr)
    from parrot.sdd.scripts.worktree_sync import stale_base_summary
    print(stale_base_summary(worktree), file=sys.stderr)
```

**Why**: The host-only call consumes TASK-5207 without breaking the stdlib-only child startup path.

### `packages/ai-parrot/tests/sdd/test_sdd_launch.py` (MODIFY)

Anchor `monkeypatch.setattr(launcher, "prepare_upstream", lambda path: "launch-worker: ready")` — packages/ai-parrot/tests/sdd/test_sdd_launch.py:172, occurrences: 2 (verified at cd57902e64).

```python
# The anchor occurs twice; scope each replacement to these two test functions:
# test_launch_brief_uses_existing_worktree_and_slug_prompt
# test_launch_non_tmux_passes_worktree_and_worker_prompt
# FILL IN: stub worktree_sync.stale_base_summary in both fixtures to avoid real fetch.
# Add tests for advisory order, skipped result continuation, no-upstream bypass,
# and preserve test_tmux_child_script_runs_without_site_packages.
```

**Why**: Existing fake worktrees are not valid repositories; tests must not leak a real fetch.

### `.claude/commands/sdd-start.md` (MODIFY)

Anchor `cd "$WT"` — .claude/commands/sdd-start.md:73, occurrences: 1 (verified at cd57902e64).

```bash
# Insert immediately after the existing cd "$WT" in host preparation step 3.
parrot sdd worktree sync-base "$WT" --dry-run || true
# Surface the advisory output verbatim and continue. Suggest host sync before the
# worker starts if base commits are missing. Never run this full-base check inside
# a sandboxed worker; there it cannot fetch and would only produce a refusal.
```

**Why**: An advisory must never integrate or stop startup; source/packaged twins remain consistent.

### `packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-start.md` (MODIFY)

Anchor `cd "$WT"` — packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-start.md:73, occurrences: 1 (verified at cd57902e64).

```bash
# Insert immediately after the existing cd "$WT" in host preparation step 3.
parrot sdd worktree sync-base "$WT" --dry-run || true
# Surface the advisory output verbatim and continue. Suggest host sync before the
# worker starts if base commits are missing. Never run this full-base check inside
# a sandboxed worker; there it cannot fetch and would only produce a refusal.
```

**Why**: An advisory must never integrate or stop startup; source/packaged twins remain consistent.

### `.agent/workflows/sdd-start.md` (MODIFY)

Anchor `cd "$WT"` — .agent/workflows/sdd-start.md:70, occurrences: 1 (verified at cd57902e64).

```bash
# Insert immediately after the existing cd "$WT" in host preparation step 3.
parrot sdd worktree sync-base "$WT" --dry-run || true
# Surface the advisory output verbatim and continue. Suggest host sync before the
# worker starts if base commits are missing. Never run this full-base check inside
# a sandboxed worker; there it cannot fetch and would only produce a refusal.
```

**Why**: An advisory must never integrate or stop startup; source/packaged twins remain consistent.

### `packages/ai-parrot/src/parrot/sdd/_assets/agent/workflows/sdd-start.md` (MODIFY)

Anchor `cd "$WT"` — packages/ai-parrot/src/parrot/sdd/_assets/agent/workflows/sdd-start.md:70, occurrences: 1 (verified at cd57902e64).

```bash
# Insert immediately after the existing cd "$WT" in host preparation step 3.
parrot sdd worktree sync-base "$WT" --dry-run || true
# Surface the advisory output verbatim and continue. Suggest host sync before the
# worker starts if base commits are missing. Never run this full-base check inside
# a sandboxed worker; there it cannot fetch and would only produce a refusal.
```

**Why**: An advisory must never integrate or stop startup; source/packaged twins remain consistent.


### FILL IN checklist

- [ ] Host launch prints the advisory after prepare_upstream and before worker launch; skipped checks still launch.
- [ ] --no-upstream skips upstream and stale-base checks; existing tmux attach paths do not introduce preparation.
- [ ] python -S child regression and CLI environment-snapshot isolation tests still pass.
- [ ] sdd-start twins run advisory dry-run after host cd, surface output and continue; sandbox worker startup never runs it.
- [ ] No new integration, push, config-write or sandbox-widening action is introduced by the advisory.

## Acceptance Criteria

- [ ] Host launch prints the advisory after prepare_upstream and before worker launch; skipped checks still launch.
- [ ] --no-upstream skips upstream and stale-base checks; existing tmux attach paths do not introduce preparation.
- [ ] python -S child regression and CLI environment-snapshot isolation tests still pass.
- [ ] sdd-start twins run advisory dry-run after host cd, surface output and continue; sandbox worker startup never runs it.
- [ ] No new integration, push, config-write or sandbox-widening action is introduced by the advisory.
- [ ] All task validation commands pass and touched Python files pass `ruff check`; apply `black --line-length 120` to touched Python files.

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_sdd_launch.py -q`
- `pytest tests/sdd_scripts/test_check_asset_sync.py -q`

## Test Specification

Cover behind/up-to-date/skipped summary presentation through the launcher seam, ordering, no-upstream, preflight failure, existing tmux attach and non-tmux launches. Reuse existing python -S and environment isolation regressions.

## Agent Instructions

1. Use `$sdd-start TASK-5211` in the FEAT-806 feature worktree; never implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/worktree-sync-base.json` and revalidate contracts before editing.
3. Implement only declared files, finish every blueprint gap, and run the listed validation commands. Store logs under `artifacts/logs/`.
4. Commit implementation files, then finalize through `scripts.sdd.finalize_task` using real `TaskCompletionEvidence` and the exact implementation HEAD, following the Codex adaptation contract. Do not manually move tasks or write completion evidence.
5. Commit only the resulting task/index state. Do not push from the worker.

## Completion Note

Pending; populated by the finalization tool after implementation and validation.
