---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling]
tags: [sdd, hooks, dangerous-actions, ledger-fix]
---

# Feature Specification: Dangerous-actions guard fixes (refspec force-push, protected-branch set)

**Feature ID**: FEAT-792
**Date**: 2026-11-03
**Author**: Jesus Lara (decisions) + Claude (`/sdd-fix`, actor `agent:sdd-fix:98973fa0`)
**Status**: approved
**Target version**: Next release (assigned by release tooling)
**Source**: ledger fix group `fixgroup:7928fe44b25c` — `issue:047c5435b564`, `issue:47b61e69475b`
(both discovered from TASK-5110 / FEAT-633 C32)

---

## 1. Motivation & Business Requirements

### Problem Statement

The portable dangerous-actions guard (`parrot.sdd.scripts.dangerous_actions`, FEAT-633 C32, served as
`parrot sdd hooks dangerous-actions --hook`) and the repo's own bash hook
(`.claude/hooks/dangerous-actions-blocker.sh`) have two open ledger findings:

1. **`issue:047c5435b564` (bug, minor).** The force-push rule only matches the `-f` / `--force` flags. A refspec
   with a leading `+` forces the update just the same — `git push origin +dev`, `git push origin +HEAD:main`,
   `git push origin +refs/heads/main` — and is allowed. Found by the TASK-5110 adversarial probe (54/55 cases
   matched; this was the miss). The bash hook has the same gap; the port copied it.
2. **`issue:47b61e69475b` (tech_debt, low).** Spec C32 (`sdd/specs/parrot-installer.spec.md` §3 M6) and
   `docs/getting-started.md` say the protected branches are `base_branch`, `staging_branch`, `hotfix_base` from
   `sdd/config.json` plus `main`/`master`. `protected_branches()` actually unions those with
   `_DEFAULT_PROTECTED = ("dev", "main", "master", "staging")`, so with `base_branch: trunk` a force-push or
   `branch -D` of `dev` is still denied. Code and docs disagree.

### Goals
- G1: Deny a `git push` whose refspec starts with `+` and whose destination is a protected branch, in both the
  Python guard and the bash hook; keep `+<feature-branch>` and `--force-with-lease` allowed.
- G2: Make spec C32, `docs/getting-started.md` and the `protected_branches()` docstring describe the code's
  actual set: the defaults `dev`, `main`, `master`, `staging` **always**, plus the three config branches.
- G3: Pin both behaviours with tests, including the bash-parity table.

### Non-Goals (explicitly out of scope)
- Changing `protected_branches()` / `_DEFAULT_PROTECTED` behaviour (decision D2).
- Making the bash hook read `sdd/config.json` (it stays ai-parrot's own hook with its fixed list).
- Any other guard rule.

---

## Governing Decisions

- **D1 — refspec rule scope.** A `git push` command is a forced update of a protected branch when any
  non-option argument after the remote starts with `+` and its destination names a protected branch. The
  destination is the part after `:` when present, else the whole refspec; a `refs/heads/` prefix is stripped
  before comparing. `+HEAD`, `+<feature>`, `+<feature>:<feature>` stay allowed. Matching uses the same
  quoted-text-stripped `scan` string as every other command-position rule.
- **D2 — protected-branch set (Jesus Lara, 2026-11-03).** Keep the code's superset: over-protecting is the safe
  direction, and in a repo whose `base_branch` is `trunk` a `dev` or `staging` branch usually still matters. The
  docs/spec follow the code; `protected_branches()` is not changed.

---

## 2. Architectural Design

### Overview
One rule is added to the existing Bash-tool branch of `evaluate()` in
`packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py`, next to the `--force` rule and sharing its
deny message; the bash hook gains the equivalent ERE check inside its force-push block. No new module, no new
dependency, no change to the hook protocol.

### Integration Points
| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.sdd.scripts.dangerous_actions.evaluate` | modifies | new `+refspec` condition beside the `--force` rule |
| `.claude/hooks/dangerous-actions-blocker.sh` | modifies | same check, fixed `main|dev|staging|master` list |
| `packages/ai-parrot/tests/sdd/test_dangerous_actions.py` | extends | DENIED / ALLOWED / PARITY tables + protected-set test |
| `sdd/specs/parrot-installer.spec.md` (C32) | docs | protected-branch sentence |
| `docs/getting-started.md` | docs | protected-branch sentence (line ~458) |

---

## 3. Module Breakdown

### Module 1: refspec force-push rule + protected-set wording (TASK-5121)
- **Files**: `dangerous_actions.py`, `dangerous-actions-blocker.sh`, `test_dangerous_actions.py`,
  `parrot-installer.spec.md`, `docs/getting-started.md`
- **Responsibility**: G1–G3 in one change (single small module; both issues touch the same guard).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_denied[git push origin +dev]` (+ `+HEAD:main`, `+refs/heads/main`, `+main` with `-u`) | M1 | refspec force to a protected branch is denied |
| `test_allowed[git push origin +feat-x]` (+ `+HEAD:feat-x`, `+feat-x:feat-x`) | M1 | refspec force to a feature branch stays allowed |
| `test_parity_with_bash_blocker[...]` | M1 | the new deny/allow cases give the same verdict in the bash hook |
| `test_default_branches_stay_protected_with_custom_base` | M1 | `base_branch: trunk` → `trunk`, `dev`, `staging`, `main`, `master` all protected |

### Validation Contract
tests:
- packages/ai-parrot/tests/sdd/test_dangerous_actions.py  # 5121
- packages/ai-parrot/tests/sdd/test_installer_dangerous_guard.py  # reads (guard registration unchanged)
markers: none

## 5. Acceptance Criteria
- [ ] `evaluate()` denies `git push origin +dev`, `git push origin +HEAD:main`, `git push origin +refs/heads/main`,
      `git push -u origin +main`; allows `git push origin +feat-x`, `git push origin +HEAD:feat-x`,
      `git push --force-with-lease origin feat-x`, `echo "git push origin +dev"`.
- [ ] The bash hook gives the same verdict for every PARITY case (exit 2 = deny).
- [ ] With `sdd/config.json` `base_branch: trunk`, `dev`/`staging`/`main`/`master`/`trunk` are protected; spec C32,
      `docs/getting-started.md` and the `protected_branches()` docstring say so.
- [ ] `protected_branches()` / `_DEFAULT_PROTECTED` unchanged (diff shows docstring only).
- [ ] `ruff check` clean on the Python file; existing guard tests still pass.

---

## 6. Codebase Contract

Verified on `origin/dev` at `995ea09c19` (2026-11-03).

```python
# packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py
_DEFAULT_PROTECTED = ("dev", "main", "master", "staging")          # line 31
def protected_branches(root: Path | None) -> tuple[str, ...]        # line 73 — docstring says "{base_branch, staging_branch, hotfix_base, main, master}"
_FORCE_FLAG = re.compile(r"(\s|^)(-f|--force)(\s|$|=)")            # line 141
def _branch_re(branches: Sequence[str]) -> str                     # line 144 — r"\b(a|b|…)\b"
# force-push rule, lines 201-214: git\s+push\b AND _FORCE_FLAG AND not --force-with-lease AND _branch_re(protected)
```
```bash
# .claude/hooks/dangerous-actions-blocker.sh lines 107-120: force-push block (fixed list main|dev|staging|master)
```
```python
# packages/ai-parrot/tests/sdd/test_dangerous_actions.py — DENIED (27), ALLOWED (60), PARITY (207), parity test (232),
# test_protected_branches_follow_sdd_config (97)
```

---

## 7. Implementation Notes & Constraints
- Shipped asset rule: the Python guard stays stdlib-only and never names repo-only fixes.
- The bash hook is ai-parrot's own (not shipped by the installer); keep its fixed branch list.

## 8. Open Questions
None — D1 and D2 decided.

---

## Revision History
| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-03 | Jesus Lara + Claude | Initial spec from ledger group `fixgroup:7928fe44b25c` (`/sdd-fix`) |
