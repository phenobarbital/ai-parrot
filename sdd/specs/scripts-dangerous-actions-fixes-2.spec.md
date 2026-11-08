---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling]
tags: [sdd, hooks, dangerous-actions, ledger-fix]
---

# Feature Specification: Dangerous-actions guard — match protected branches as whole tokens

**Feature ID**: FEAT-839
**Date**: 2026-11-07
**Author**: Jesus Lara (decisions) + Claude (`/sdd-fix`, actor `agent:sdd-fix:6fbaeb1b`)
**Status**: approved
**Target version**: Next release (assigned by release tooling)
**Source**: ledger fix group `fixgroup:50cf621ba546` — `issue:a682edf559a5` (discovered from FEAT-837;
supersedes the closed `issue:b53036501784`)

---

## 1. Motivation & Business Requirements

### Problem Statement

During FEAT-837 cleanup, `git branch -d feat-FEAT-837-dev-loop-feature-launcher-fixes` (already merged) was denied
as "Deleting a protected branch (main/dev/staging)". The protected-branch pattern is `\b(main|dev|staging|master)\b`;
a hyphen is a word boundary, so the `dev` segment of `...-dev-loop-...` matches as the protected `dev` branch.
The same pattern sits in the Python guard (`_branch_re()`, used by the branch-delete and `--force` push rules)
and in the repo's bash hook (`.claude/hooks/dangerous-actions-blocker.sh`, force-push check and branch-delete
check). It fails closed, but blocks cleanup of any branch with a dev/main/staging/master segment and pushes users
toward `PARROT_ALLOW_DANGEROUS=1`.

### Goals
- G1: A protected name matches only as a whole branch token — not preceded or followed by a letter, digit, `_`,
  `.`, `/` or `-` — with an optional `refs/heads/` prefix, in the Python guard and the bash hook.
- G2: branch delete (`-d`/`-D`) and flag force-push (`-f`/`--force`) of `feat-X-dev-loop-y`, `fix-main-menu`,
  `feat/dev` are allowed; the same commands on `dev`, `main`, `refs/heads/main`, `HEAD:main`, `dev:dev` stay denied.
- G3: Pin both with tests, including the bash-parity table.

### Non-Goals (explicitly out of scope)
- Changing the protected set (`protected_branches()` / `_DEFAULT_PROTECTED`).
- The `+refspec` force-push rule (already token-exact) and every other guard rule.
- Parsing branch arguments out of the command; the rules stay regex scans over the quoted-text-stripped line.

---

## Governing Decisions

- **D1 — token boundary.** The boundary class is `[A-Za-z0-9_./-]` (Python: `[\w./-]` via lookarounds; bash ERE:
  `(^|[^[:alnum:]_./-])` … `($|[^[:alnum:]_./-])`). `:`, `+`, whitespace and shell separators are boundaries, so
  `HEAD:main`, `dev:dev` and `+main` still match. `refs/heads/<name>` is matched explicitly because `/` is not a
  boundary. A protected word elsewhere in a flag-forced push line (`cd dev && <forced push of feat>`) still denies —
  the rule keeps failing closed.

---

## 2. Architectural Design

### Overview
`_branch_re()` changes its boundaries; its two callers (force-push and branch-delete rules) pick that up
unchanged. The bash hook's two `\b(main|dev|staging|master)\b` checks get the equivalent ERE. No new module.

### Integration Points
| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.sdd.scripts.dangerous_actions._branch_re` | modifies | token boundaries + optional `refs/heads/` |
| `.claude/hooks/dangerous-actions-blocker.sh` | modifies | force-push check (line 123) and branch-delete check (line 142) |
| `packages/ai-parrot/tests/sdd/test_dangerous_actions.py` | extends | DENIED / ALLOWED / PARITY cases |

---

## 3. Module Breakdown

### Module 1: whole-token protected-branch match (TASK-5299)
- **Files**: `dangerous_actions.py`, `dangerous-actions-blocker.sh`, `test_dangerous_actions.py`
- **Responsibility**: G1–G3.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_denied[...]`: delete of `main`, `dev`, `refs/heads/main`; forced push of `HEAD:main`, `dev:dev` | M1 | protected targets still denied |
| `test_allowed[...]`: delete of `feat-FEAT-837-dev-loop-feature-launcher-fixes`, `fix-main-menu`, `feat/dev`; forced push of `feat-x-dev-loop`, `fix-main-menu` | M1 | segment matches no longer denied |
| `test_parity_with_bash_blocker[...]` | M1 | the same cases give the same verdict in the bash hook |

### Validation Contract
tests:
- packages/ai-parrot/tests/sdd/test_dangerous_actions.py  # 5299
- packages/ai-parrot/tests/sdd/test_installer_dangerous_guard.py  # reads (guard registration unchanged)
markers: none

## 5. Acceptance Criteria
- [ ] `evaluate()` allows branch delete of `feat-FEAT-837-dev-loop-feature-launcher-fixes`, `fix-main-menu`,
      `feat/dev`, and `-f`/`--force` push of `feat-x-dev-loop` and `fix-main-menu`.
- [ ] `evaluate()` still denies branch delete of `main`, `dev`, `refs/heads/main`, `-f`/`--force` push of
      `HEAD:main` and `dev:dev`, and every existing DENIED case.
- [ ] The bash hook gives the same verdict for every new PARITY case (exit 2 = deny).
- [ ] `ruff check` clean on the Python file; `bash -n` ok on the hook; existing guard tests pass.

---

## 6. Codebase Contract

Verified on `origin/dev` at `15a0e9d19d` (2026-11-07).

```python
# packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py
def _branch_re(branches: Sequence[str]) -> str                     # line 149 — r"\b(a|b|…)\b"
# force-push rule, line 231: … and re.search(_branch_re(protected), scan)
# branch-delete rule, line 252: git\s+branch\s+[^;&|]*-[dD]\b[^;&|]* + _branch_re(protected)
```
```bash
# .claude/hooks/dangerous-actions-blocker.sh
# line 123: \b(main|dev|staging|master)\b                          (force-push block)
# line 142: git\s+branch\s+[^;&|]*-[dD]\b[^;&|]*\b(main|dev|staging|master)\b
```
```python
# packages/ai-parrot/tests/sdd/test_dangerous_actions.py — DENIED (27), ALLOWED (67), PARITY (264), parity test (292)
```

---

## 7. Implementation Notes & Constraints
- The Python guard is a shipped asset: stdlib-only, no repo-only names.
- The bash hook keeps its fixed `main|dev|staging|master` list.

## 8. Open Questions
None — D1 decided.

---

## Revision History
| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-07 | Jesus Lara + Claude | Initial spec from ledger group `fixgroup:50cf621ba546` (`/sdd-fix`) |
