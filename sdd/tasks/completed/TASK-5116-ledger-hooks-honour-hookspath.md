# TASK-5116: ledger git hooks honour core.hooksPath; sdd uninstall scoped to the receipt

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md` (rev 0.12 — ledger fixes)
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5115
**Assigned-to**: unassigned
**Discovered-from**: `issue:4c5b3404e8fb`

---

## Context

`claude_code/installer.py::_git_hook_path` resolves hooks under `.git/hooks` (or the common dir of a linked
worktree) and never consults `core.hooksPath`. In a repo using husky/lefthook or a shared hooks dir, the four
`parrot-ledger` hooks (and the wiki post-commit hook) are written where git never runs them, and doctor's
`sdd: ledger hooks` check, which uses the same helper, still reports them present. Also, `parrot sdd uninstall`
calls `_uninstall_ledger_hooks(root)`, which strips the block from all four events even though the receipt records
only the events this integration created (`receipt["ledger_hooks"]`).

Verified with git 2.43 (2026-11-03): `git -C <root> rev-parse --show-toplevel --git-path hooks/<event>` returns
`.git/hooks/<event>` by default, `<hooksPath>/<event>` (relative to the worktree root, or absolute) when
`core.hooksPath` is set, and the common-dir hooks path from a linked worktree.

---

## Scope

- `_git_hook_path(root, hook_name)` asks git first (`rev-parse --show-toplevel --git-path hooks/<name>`, bounded
  timeout, no prompt). It uses the answer only when the toplevel resolves to `root`; a relative path resolves
  against `root`. Otherwise (git missing or failing, or a fake `.git` dir in tests) it falls back to the current
  file-based logic unchanged.
- `_uninstall_ledger_hooks(root, events=None)`: `None` keeps today's behaviour (all four events: claude uninstall);
  an iterable limits the strip to those events. `parrot sdd uninstall` passes `receipt["ledger_hooks"]`.
- Doctor's `sdd: ledger hooks` inherits the fix through `_git_hook_path`; its detail names the hooks directory.

**NOT in scope**: husky/lefthook-specific wrappers; changing `PlannedAction` target labels (`.git/hooks`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | MODIFY | `_git_hook_path` via git; `_uninstall_ledger_hooks(events=)` |
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | `ledger-hooks-remove` passes the receipt events |
| `packages/ai-parrot/src/parrot/self_/doctor.py` | MODIFY | ledger-hooks detail names the hooks dir |
| `tests/knowledge/wiki/test_installer_ledger_hooks.py` | MODIFY | hooksPath + scoped-uninstall tests |
| `packages/ai-parrot/tests/self_/test_doctor_sdd.py` | MODIFY | doctor follows core.hooksPath |

---

## Codebase Contract (Anti-Hallucination)

Verified on `feat-FEAT-633-parrot-installer` at `3d66594c6b` (2026-11-03).

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
def _git_hook_path(root: Path, hook_name: str = "post-commit") -> Optional[Path]   # line 926
def _install_ledger_hooks(root: Path) -> list[str]                                  # line 1080
def _uninstall_ledger_hooks(root: Path) -> list[str]                                # line 1125
# callers of _git_hook_path: claude installer 1020/1085/1129/1382/1446; sdd/installer.py 622/631/830; doctor.py 341
# packages/ai-parrot/src/parrot/sdd/installer.py
#   uninstall step "ledger-hooks-remove" at line 1181: actions.extend(_uninstall_ledger_hooks(root))
# packages/ai-parrot/src/parrot/self_/doctor.py
def _check_ledger_hooks(root: Path) -> DoctorCheck                                   # line 333
```

---

## Acceptance Criteria

- [ ] With `core.hooksPath=.husky`, `_install_ledger_hooks` writes the four blocks under `.husky/`, nothing under
      `.git/hooks/`, and doctor's `sdd: ledger hooks` fails when `.husky/` lacks them even if `.git/hooks/` has them.
- [ ] Linked-worktree and fake-`.git` behaviour is unchanged (existing tests pass).
- [ ] `parrot sdd uninstall` strips only the events in `receipt["ledger_hooks"]`.
- [ ] `ruff check` clean.

## Validation Commands

- `pytest tests/knowledge/wiki/test_installer_ledger_hooks.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_installer.py -q`
- `pytest packages/ai-parrot/tests/self_/test_doctor_sdd.py -q`
- `pytest tests/knowledge/wiki/test_claude_code.py -q`

## Agent Instructions

Work in `feat-FEAT-633-parrot-installer`; run tests with `PYTHONPATH=packages/ai-parrot/src`; stage only the files
above; close with `parrot sdd task close TASK-5116 parrot-installer verified`.

---

## Completion Note
**Completed by**: Claude Opus 5.5 (/sdd-fix, sequential)
**Date**: 2026-11-03
**Notes**: `_git_resolved_hook_path` runs `git -C root rev-parse --show-toplevel --git-path hooks/<name>` (10 s timeout, no prompt) and is used only when the toplevel resolves to root; relative answers resolve against root. Fake-`.git` test repos fall back to the old lookup unchanged. `_uninstall_ledger_hooks(root, events=None)`; sdd uninstall passes `receipt["ledger_hooks"]`. Doctor detail names the hooks dir. 5 new tests; 283 passed across every hook-related suite (claude/codex installers, worktree guard, install_hooks, sdd installer, ledger outbox) + doctor_sdd; ruff clean.
