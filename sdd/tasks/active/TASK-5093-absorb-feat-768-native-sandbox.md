# TASK-5093: Absorb FEAT-768 — move the native sandbox next to the packaged hook

**Feature**: FEAT-633 — parrot-installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5092, TASK-5095, TASK-5097, TASK-5098 — and, **external** (cannot be expressed in `depends_on`): PR #1884 (FEAT-768,
including TASK-5086..5089) merged into `dev`. Do not start before `git merge-base --is-ancestor
origin/feat-FEAT-768-sdd-claude-native-sandbox origin/dev` succeeds.
**Assigned-to**: unassigned

---

## Context

Decision 2026-11-01: FEAT-768 (native Claude sandbox) merges to `dev` first, and FEAT-633 absorbs it, because
FEAT-633 is the change that relocates the SDD hook. FEAT-633 moved `worktree_environment.py` to
`parrot/sdd/scripts/` and left `parrot/flows/dev_loop/worktree_environment.py` as a `runpy`/`sys.modules` shim.
FEAT-768 adds its native backend to the *old* path and imports `native_claude_sandbox` as a script **sibling**
(`import native_claude_sandbox` when `__package__` is empty). Once both are on one branch the sibling import
breaks and every native-mode hook call is denied. Tracked as ledger `issue:3253d3dc39b0`; this task resolves it.

---

## Scope

1. `git merge origin/dev` (brings FEAT-768). Resolve `parrot/flows/dev_loop/worktree_environment.py` by keeping
   FEAT-633's shim and porting FEAT-768's changes (native backend in `hook_response`, the native-marker guard in
   `main()`, the degraded banner, the actionable bwrap message, the Windows-safe `CLAUDE_SCRATCH_ROOT`) into
   `parrot/sdd/scripts/worktree_environment.py`.
2. Move `parrot/flows/dev_loop/native_claude_sandbox.py` to `parrot/sdd/scripts/native_claude_sandbox.py` and
   leave a compatibility shim at the old path in the same style as the other FEAT-633 shims (importers such as
   `dispatchers/claude.py`, `models/claude.py` and `feature_launcher.py` keep working; running it as a script
   still serves `launch-worker`). The sibling import in both modules now resolves inside `parrot/sdd/scripts/`.
3. Control paths: `_denied_write_paths` and `_control_path` hard-code
   `packages/ai-parrot/src/parrot/flows/dev_loop/{native_claude_sandbox,worktree_environment}.py`. Protect the
   relocated real files **and** keep the shims protected; in a consumer repository (no `packages/` tree) protect
   the files the hook actually runs from (resolve them from `Path(__file__)`, not from the repo layout).
4. Hook command: FEAT-633's agent frontmatter runs `parrot sdd worktree guard --hook || exit 2` (C26 / TASK-5097);
   FEAT-768's compiled settings run `<sys.executable> <module file> --hook || exit 2`. Make the compiled
   settings use the same entry point FEAT-633 ships (or document in the Completion Note why the interpreter form
   must stay — e.g. the launcher's interpreter is the one whose policy is compiled), and keep both hook paths
   denying when the backend markers are inconsistent.
5. `parrot/flows/dev_loop/feature_launcher.py` (TASK-5088) invokes `python -m scripts.sdd.ensure_worktree` with
   `cwd=<primary>`: repoint it to the packaged runner (`parrot.sdd.scripts.ensure_worktree`) so it works in
   consumer repositories.
6. ~~Add `parrot sdd launch-worker` as an alias of `parrot devloop launch-worker`~~ — **superseded by
   TASK-5100 (C26)**: the launcher is mounted as `parrot sdd launch worker` and the `devloop` registration is
   deleted there. This task leaves `parrot devloop launch-worker` as merged and touches no CLI file.
7. `scripts/sdd/launch_worker.sh` calls `$repo_root/packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py`;
   keep it working through the shim (monorepo-only script; it is not shipped in `_assets`).
8. `python scripts/sdd/check_asset_sync.py --write` if any shipped asset changed (agent frontmatter, docs).
9. Add `packages/ai-parrot/tests/cli/devloop/test_launch_worker_cmd.py` (it exists only after the merge) to the spec's
   Validation Contract and re-run `python scripts/sdd/cache_test_contract.py --spec sdd/specs/parrot-installer.spec.md --index sdd/tasks/index/parrot-installer.json`.
10. Close the ledger issue: `wikitoolkit ledger close issue:3253d3dc39b0 --resolved-by <commit>` (use the full
   `issue:` prefix; confirm with `ledger show`).

**NOT in scope**: changing FEAT-768 sandbox semantics (modes, probes, policy); the live qualification; new
installer features; deleting the shims.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` | MODIFY | port FEAT-768's hook changes |
| `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py` | MODIFY | keep as shim (merge resolution) |
| `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` | CREATE | moved implementation |
| `packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py` | MODIFY | becomes a shim |
| `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` | MODIFY | packaged `ensure_worktree` runner |
| `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` | MODIFY | control paths after the move; sibling import as script |
| `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` | MODIFY | hook via the packaged path in native mode |
| `packages/ai-parrot/src/parrot/sdd/_assets/**` | MODIFY | regenerated if a shipped source changed |
| `sdd/specs/parrot-installer.spec.md` | MODIFY | Validation Contract gains `test_launch_worker_cmd.py` |
| `sdd/tasks/index/parrot-installer.json` | MODIFY | re-cached test contract |

---

## Codebase Contract (Anti-Hallucination)

> FEAT-768's side of this contract describes code that is **not yet on this branch**: re-verify every entry
> after the step-1 merge and update the contract before editing if anything moved.

### Verified Imports
```python
# FEAT-633 (this branch):
from parrot.sdd.scripts import worktree_environment as _impl   # parrot/flows/dev_loop/worktree_environment.py shim
# FEAT-768 (origin/feat-FEAT-768-sdd-claude-native-sandbox @ 85db9a6c82):
from parrot.flows.dev_loop import native_claude_sandbox, worktree_environment   # dispatchers/claude.py:66
# native_claude_sandbox.py:22-25 — `from . import worktree_environment as _we` / `import worktree_environment as _we`
```

### Existing Signatures to Use
```text
FEAT-633: parrot/flows/dev_loop/worktree_environment.py — shim: `runpy.run_path(<parrot>/sdd/scripts/worktree_environment.py, run_name="__main__")` as script, `sys.modules[__name__] = _impl` on import
FEAT-633: .claude/agents/sdd-worker.md hook — 'parrot sdd worktree guard --hook || exit 2' (TASK-5097; was `… run worktree_environment --hook`)
FEAT-768: native_claude_sandbox.py — _denied_write_paths(root, git_dir) (172, controls at 175-181), _control_path(root, target) (378),
  native_sandbox_settings(...) hook_command = shlex.join([sys.executable, str(Path(_we.__file__).resolve()), "--hook"]) + " || exit 2" (323)
FEAT-768: worktree_environment.py — hook_response(payload, *, backend) (502), main() (553), native import at 512-515
FEAT-768 TASK-5088 (to be written): feature_launcher.ensure_feature_worktree runs [sys.executable, "-m", "scripts.sdd.ensure_worktree", ...]
```

### Does NOT Exist
- ~~`parrot/sdd/scripts/native_claude_sandbox.py`~~ — created by this task.
- ~~a cross-feature `depends_on`~~ — `check_task_graph` rejects unknown ids, hence the external dependency in the header.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- The hook must stay stdlib-only and runnable as a plain script: keep the `if __package__ … else import …`
  sibling pattern, now inside `parrot/sdd/scripts/`.
- After the move, re-run FEAT-768's unit suites (they are the regression contract for the sandbox) in addition
  to FEAT-633's.
- The live qualification (`test_native_claude_sandbox_live.py`) is not re-run here; note in the Completion Note
  that the hook path changed, which by FEAT-768 policy 9 means the qualification should be re-run before release.

---

## Acceptance Criteria

- [ ] Native-mode hook calls succeed through `parrot sdd worktree guard --hook` and through the compiled settings (no `ImportError` denial).
- [ ] Old import paths (`parrot.flows.dev_loop.native_claude_sandbox`, `…worktree_environment`) still work.
- [ ] Bash and file tools cannot write the relocated real files or the shims in native mode.
- [ ] `feature_launcher` uses the packaged `ensure_worktree`; `parrot sdd launch-worker --help` works and forwards to the same function.
- [ ] `check_asset_sync.py --check` exits 0; `issue:3253d3dc39b0` closed.
- [ ] All Validation Commands green.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py -q`
- `pytest tests/sdd/test_launch_worker.py -q`
- `pytest packages/ai-parrot/tests/cli/devloop/test_launch_worker_cmd.py -q`
- `pytest tests/sdd_scripts/test_check_asset_sync.py -q`

---

## Test Specification

Extend the existing suites: a script-mode import test for `parrot/sdd/scripts/native_claude_sandbox.py`
(sibling import), a control-path test proving the relocated files and the shims are denied, a hook test running
the packaged entry point with `PARROT_SDD_SANDBOX_BACKEND=claude-native`, and a CLI test for the `sdd
launch-worker` alias.

---

## Agent Instructions

0. **Launch with the branch on `PYTHONPATH`.** This branch's agent hooks run `parrot sdd run worktree_environment --hook`;
   the shared `.venv` is editable-installed against the main checkout (`dev`), which has no `parrot sdd`, so every
   Bash call is denied. Start the session from this worktree with
   `PYTHONPATH=$PWD/packages/ai-parrot/src claude --setting-sources project,local` (or prefix `scripts/sdd/launch_worker.sh`
   the same way). Never `uv sync` inside the worktree.
1. Check the external dependency first; if PR #1884 is not merged into `dev`, stop and report.
2. Work only in the FEAT-633 worktree; commit only the files in the table (plus the merge commit).
3. Re-verify the Codebase Contract after the merge; update it before editing if anything is stale.
4. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
