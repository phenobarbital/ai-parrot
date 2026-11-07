# TASK-5299: Match protected branches as whole tokens in the dangerous-actions guard

**Feature**: FEAT-839 — Dangerous-actions guard: whole-token protected-branch match
**Spec**: `sdd/specs/scripts-dangerous-actions-fixes-2.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: agent:sdd-fix:6fbaeb1b
**Discovered-from**: `issue:a682edf559a5`

---

## Context

Ledger group `fixgroup:50cf621ba546` (`/sdd-fix`): deleting the merged branch
`feat-FEAT-837-dev-loop-feature-launcher-fixes` was denied as a protected-branch delete, because
`\b(main|dev|staging|master)\b` treats the hyphen-delimited `dev` segment as the `dev` branch. Spec decision D1
(token boundary class `[A-Za-z0-9_./-]`, optional `refs/heads/`) is binding.

## Scope

- `_branch_re()` in `dangerous_actions.py`: build
  `(?<![\w./-])(?:refs/heads/)?(<escaped names>)(?![\w./-])`. Both callers stay as they are.
- `.claude/hooks/dangerous-actions-blocker.sh`: replace `\b(main|dev|staging|master)\b` in the force-push check
  (line 123) and the branch-delete check (line 142) with
  `(^|[^[:alnum:]_./-])(refs/heads/)?(main|dev|staging|master)($|[^[:alnum:]_./-])`.
- Tests in `test_dangerous_actions.py`: the spec §5 deny cases into `DENIED`, the allow cases into `ALLOWED`, and
  both sets into `PARITY`.

**NOT in scope**: the protected set; the `+refspec` rule; other guard rules.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py` | MODIFY | `_branch_re()` token boundaries |
| `.claude/hooks/dangerous-actions-blocker.sh` | MODIFY | same boundaries, lines 123 and 142 |
| `packages/ai-parrot/tests/sdd/test_dangerous_actions.py` | MODIFY | DENIED / ALLOWED / PARITY cases |

## Codebase Contract (Anti-Hallucination)

Verified on `origin/dev` at `15a0e9d19d` (2026-11-07).

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py
def _branch_re(branches: Sequence[str]) -> str                     # line 149
#   callers: force-push rule (line 231) and branch-delete rule (line 252), both inside _bash()
# .claude/hooks/dangerous-actions-blocker.sh — force-push check line 123, branch-delete check line 142
# packages/ai-parrot/tests/sdd/test_dangerous_actions.py — DENIED line 27, ALLOWED line 67, PARITY line 264,
#   test_parity_with_bash_blocker line 292 (skips without bash/jq/repo hook)
```

### Does NOT Exist
- ~~a branch-argument parser in the guard~~ — stay with the regex scan

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py", "action": "MODIFY"},
    {"path": ".claude/hooks/dangerous-actions-blocker.sh", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_dangerous_actions.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py#_branch_re"
  ]
}
```

## Acceptance Criteria
- [ ] Spec §5 criteria met.

## Validation Commands
- `pytest packages/ai-parrot/tests/sdd/test_dangerous_actions.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_installer_dangerous_guard.py -q`

## Agent Instructions
Work in the `feat-FEAT-839-scripts-dangerous-actions-fixes-2` worktree; run tests with
`PYTHONPATH=packages/ai-parrot/src`; commit only the files above; close with
`parrot sdd task close TASK-5299 scripts-dangerous-actions-fixes-2 verified`.

## Completion Note
*(Agent fills this in when done)*
