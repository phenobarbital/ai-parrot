# TASK-5218: sync-base sandbox reachability check, clean OSError refusal, rollback-result helper

**Feature**: FEAT-813 — sync-base sandbox reachability check, clean OSError refusal, and host-provisioned push protection
**Spec**: `sdd/specs/scripts-worktree-sync-tech-debt.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:e613f365cf61`, `issue:891a632132e0`

---

## Context

Implements spec §2 P1, P2 and P4 (AC1, AC2, AC3, AC9). The sandbox path of `sync-base` applies
any existing single-parent commit, even one not on the base branch; `main()` crashes with a
traceback when `git`/`gh` is missing; the rollback-result block is duplicated.

---

## Scope

- `_sandbox_patches(wt, cherry_picks, base)`: add a GitHub compare check per commit.
- `sync()`: pass `base` to `_sandbox_patches`; replace both duplicated rollback/result blocks with
  one `_integration_failure(...)` helper.
- `main()`: also catch `(OSError, subprocess.SubprocessError)` → exit-5 refusal.
- Comment on `EXIT_TARGET` and a docs note that exit 2 is also argparse's usage-error code.
- Tests.

**NOT in scope**: push-protection provisioning (TASK-5219); changing exit-code values; host path
semantics.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py` | MODIFY | P1, P2, P4 |
| `tests/sdd_scripts/test_worktree_sync.py` | MODIFY | gh stub serves compare; new tests |
| `docs/sdd/worktree-sync-base.md` | MODIFY | exit-code-2 note + sandbox reachability sentence |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports / Symbols (origin/dev `b1b7585561`)
- `worktree_sync._gh(wt: Path, endpoint: str, *, patch: bool = False) -> str` — raises `SyncError(EXIT_TRANSPORT, …)` on non-zero exit.
- `worktree_sync._sandbox_patches(wt: Path, cherry_picks: Sequence[str]) -> list[tuple[str, str]]` — called once in `sync()`.
- `worktree_sync.owner_repo(wt) -> str` (`owner/repo`), `_sandbox_hint(detail) -> str`.
- `worktree_sync._rollback(wt, before, command) -> tuple[bool, list[str], str]`.
- `worktree_sync._result(wt, base, mode, dry_run, before, commits, status, code, message, conflicts=None) -> SyncResult`.
- `worktree_sync._refusal(target, base, exc: SyncError, dry_run) -> SyncResult`.
- Constants: `EXIT_OK, EXIT_TARGET, EXIT_DIRTY, EXIT_LIVE, EXIT_TRANSPORT, EXIT_CONFLICT = 0, 2, 3, 4, 5, 6`.
- Test helpers in `tests/sdd_scripts/test_worktree_sync.py`: `_repository`, `_configure_sandbox`, `_install_gh_stub(tmp_path, monkeypatch, responses)`, `_patch_response(primary, sha)`. The stub extracts `sha=${endpoint##*/}`, so a compare endpoint `repos/o/r/compare/dev...<sha>` yields `dev...<sha>`.

### GitHub API
- `GET /repos/{owner}/{repo}/compare/{base}...{head}` → JSON with `status` ∈ `ahead|behind|diverged|identical` (head relative to base). Ancestor-or-equal ⇔ `behind|identical`.

### Does NOT Exist
- ~~`worktree_sync._integration_failure`~~ — created here.
- ~~compare fixtures in the gh stub~~ — added here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_worktree_sync.py", "action": "MODIFY"},
    {"path": "docs/sdd/worktree-sync-base.md", "action": "MODIFY"}
  ],
  "contract_symbols": ["_sandbox_patches", "_integration_failure", "main", "sync"]
}
```

---

## Implementation Notes

- The compare check goes inside the existing per-commit loop, after metadata validation and before
  the patch download, so every refusal happens before any worktree mutation (dry run included).
- Use `_gh(wt, f"repos/{repository}/compare/{base}...{source_sha}")`; `json.JSONDecodeError` or a
  non-dict body → same "not reachable" refusal (fail closed).
- Message: `_sandbox_hint(f"cherry-pick {requested} is not reachable from origin/{base}")`.
- `_integration_failure(wt, base, mode, before, commits, abort_command) -> SyncResult` returns the
  verified-conflict result or the unverified-recovery error result exactly as today.
- In the gh stub, route `*/compare/*` endpoints to `$GH_FIXTURES/compare-<sha>.json` (the part after
  `...`), and have `_install_gh_stub` write a `{"status": "behind"}` compare fixture for every sha
  by default, with an optional `compare: dict[str, str]` override parameter.

---

## Acceptance Criteria

- [ ] AC1: sandbox `ahead`/`diverged` → `SyncError` exit 5, "not reachable", tree unchanged (normal and dry run).
- [ ] AC2: `behind`/`identical` still sync; existing sandbox tests green.
- [ ] AC3: `main()` with no `git` on `PATH` returns 5; `--json` prints a `refused` result.
- [ ] AC9: conflict / unverified-rollback tests green.

---

## Validation Commands

Run with `PYTHONPATH=packages/ai-parrot/src` from the worktree.

- `pytest tests/sdd_scripts/test_worktree_sync.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_sdd_cli.py -q -k sync_base`

---

## Test Specification

- `test_sandbox_unreachable_cherry_pick_refuses` (parametrize `ahead`, `diverged`; plus `dry_run=True`).
- `test_sandbox_identical_compare_syncs`.
- `test_main_missing_git_is_clean_refusal` (PATH without git; `--json` body has `status == "refused"`, `exit_code == 5`).

---

## Agent Instructions

Work inside the FEAT-813 worktree. Touch only the files listed. Run the validation commands with
`PYTHONPATH` set to the worktree's package source. `ruff check --fix` the changed Python files.

---

## Completion Note

(filled on close)
