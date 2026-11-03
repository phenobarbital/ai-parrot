# TASK-5121: Deny `+refspec` force-push to protected branches; document the protected-branch set

**Feature**: FEAT-792 — Dangerous-actions guard fixes
**Spec**: `sdd/specs/scripts-dangerous-actions-fixes.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: agent:sdd-fix:98973fa0
**Discovered-from**: `issue:047c5435b564`
**Discovered-from**: `issue:47b61e69475b`

---

## Context

Ledger group `fixgroup:7928fe44b25c` (`/sdd-fix`, both found while verifying TASK-5110 / FEAT-633 C32):
`issue:047c5435b564` — `git push origin +dev` forces a protected branch but is allowed (only `-f`/`--force` are
matched), in the Python guard and in the repo's bash hook; `issue:47b61e69475b` — spec C32 and
`docs/getting-started.md` describe a narrower protected-branch set than `protected_branches()` enforces. Spec
decisions D1 (refspec scope) and D2 (keep the code's superset, fix the docs) are binding.

## Scope

- In `dangerous_actions.py`, deny a `git push` when any non-option argument starts with `+` and its destination
  (after `:` if present, else the whole refspec; `refs/heads/` stripped) is in `protected`. Same deny message as
  the `--force` rule. Use the quoted-text-stripped `scan`.
- Fix the `protected_branches()` docstring to state the real set (defaults `dev`, `main`, `master`, `staging`
  always, plus `base_branch`/`staging_branch`/`hotfix_base` from `sdd/config.json`). Do not change its code.
- In `.claude/hooks/dangerous-actions-blocker.sh`, add the same check to the force-push block (fixed list
  `main|dev|staging|master`, `refs/heads/` optional), keeping `--force-with-lease` excluded.
- Tests in `test_dangerous_actions.py`: add the deny/allow cases of the spec's acceptance criteria to `DENIED` /
  `ALLOWED`, add `git push origin +dev`, `git push origin +HEAD:main` and `git push origin +feat-x` to `PARITY`, and
  add `test_default_branches_stay_protected_with_custom_base`.
- Docs: spec C32 sentence in `sdd/specs/parrot-installer.spec.md` (lines 741-742) and
  `docs/getting-started.md` (line ~458).

**NOT in scope**: changing `_DEFAULT_PROTECTED` / `protected_branches()` logic; making the bash hook read config;
other guard rules.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py` | MODIFY | `+refspec` rule; docstring |
| `.claude/hooks/dangerous-actions-blocker.sh` | MODIFY | same rule in the force-push block |
| `packages/ai-parrot/tests/sdd/test_dangerous_actions.py` | MODIFY | DENIED/ALLOWED/PARITY + protected-set test |
| `sdd/specs/parrot-installer.spec.md` | MODIFY | C32 protected-branch sentence |
| `docs/getting-started.md` | MODIFY | protected-branch sentence |

## Codebase Contract (Anti-Hallucination)

Verified on `origin/dev` at `995ea09c19` (2026-11-03).

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py
_DEFAULT_PROTECTED = ("dev", "main", "master", "staging")          # line 31
def protected_branches(root: Path | None) -> tuple[str, ...]        # line 73
_FORCE_FLAG = re.compile(r"(\s|^)(-f|--force)(\s|$|=)")            # line 141
def _branch_re(branches: Sequence[str]) -> str                     # line 144
#   force-push rule (lines 201-214) inside the Bash branch of evaluate(); returns _deny(<what>, <fix lines…>)
# .claude/hooks/dangerous-actions-blocker.sh — force-push block lines 107-120
# packages/ai-parrot/tests/sdd/test_dangerous_actions.py — DENIED line 27, ALLOWED line 60, PARITY line 207,
#   test_parity_with_bash_blocker line 232 (skips without bash/jq/repo hook), test_protected_branches_follow_sdd_config line 97
```

### Does NOT Exist
- ~~a refspec parser in the guard~~ — add a small private helper; no new dependency

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py", "action": "MODIFY"},
    {"path": ".claude/hooks/dangerous-actions-blocker.sh", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_dangerous_actions.py", "action": "MODIFY"},
    {"path": "sdd/specs/parrot-installer.spec.md", "action": "MODIFY"},
    {"path": "docs/getting-started.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py#protected_branches",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py#evaluate"
  ]
}
```

## Acceptance Criteria
- [ ] Spec §5 criteria met.
- [ ] `git diff` of `protected_branches()` shows the docstring only.

## Validation Commands
- `pytest packages/ai-parrot/tests/sdd/test_dangerous_actions.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_installer_dangerous_guard.py -q`

## Agent Instructions
Work in `.claude/worktrees/feat-FEAT-792-scripts-dangerous-actions-fixes`; run tests with
`PYTHONPATH=packages/ai-parrot/src`; commit only the files above; close with
`parrot sdd task close TASK-5121 scripts-dangerous-actions-fixes verified`.

## Completion Note
*(Agent fills this in when done)*

**Completed by**: Claude Opus 5.5 (`/sdd-fix`, actor `agent:sdd-fix:98973fa0`)
**Date**: 2026-11-03
**Notes**: Implementing commit `11cc37ef2c`. `_forced_refspec_targets()` reads the `+<refspec>` arguments of every
`git … push` segment (destination after `:`, `refs/heads/` stripped); the force-push rule now denies when either the
old `--force` condition or a forced refspec targets a protected branch. `+` to a protected branch is denied even with
`--force-with-lease` (the `+` overrides the lease). The bash hook gained the same check (fixed
`main|dev|staging|master` list). `protected_branches()` logic unchanged — docstring, spec C32 and
`docs/getting-started.md` now describe the superset (D2).
Validation: `test_dangerous_actions.py` + `test_installer_dangerous_guard.py` 112 passed, none skipped — the 3 new
PARITY cases ran against this worktree's bash hook. `ruff check` clean, `bash -n` ok, `check_asset_sync --check` ok.
Pre-existing, not caused here: `test_getting_started_claims.py::test_hello_world_snippet_executes` fails only when run
after `test_check_asset_sync.py` + `test_command_twin_parity.py` + `test_no_repo_script_refs.py` in one session
(`importlib.metadata` AttributeError); the same 4-file run fails identically on the base `c23fc82532`, and the test
passes alone or with its own file.
