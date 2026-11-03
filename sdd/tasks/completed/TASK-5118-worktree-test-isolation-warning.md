# TASK-5118: warn when worktree tests would import the main checkout (sdd install note + doctor check)

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md` (rev 0.12 — ledger fixes)
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5117
**Assigned-to**: unassigned
**Discovered-from**: `issue:80c5e6e510b2`

---

## Context

SDD runs each task's tests inside `.claude/worktrees/<feature>/`, but a foreign repo's shared `.venv` usually has
the project installed editable from the MAIN checkout. `uv run --no-sync pytest` in a worktree then silently imports
the main checkout's code. ai-parrot works around the same trap with `PYTHONPATH=packages/<dist>/src`. A virtual
project (`[tool.uv] package = false`) fails the other way: its modules are not importable from pytest at all. Seen
2026-11-03 in the sandbox project (FEAT-2 `/sdd-spec`): the fix there was `[tool.pytest.ini_options] pythonpath =
["."]`, which is rootdir-relative, so each worktree tests its own code.

---

## Scope

- `parrot/sdd/installer.py::worktree_test_isolation(root, test_command) -> str | None`: read-only, never raises.
  Returns `None` for non-Python repos (no `pyproject.toml` / `setup.py` / `setup.cfg`), when `test_command` is set
  and either does not run pytest or already sets `PYTHONPATH`, and when pytest has a `pythonpath` setting
  (`pyproject.toml` `[tool.pytest.ini_options]` or `[tool.pytest]`, `pytest.ini` / `tox.ini` `[pytest]`,
  `setup.cfg` `[tool:pytest]`). Otherwise it returns one sentence that names the cause (an editable install in
  `<root>/.venv` pointing at the main checkout, per PEP 610 `direct_url.json`; a virtual project; or no
  `pythonpath`) and recommends `pythonpath = ["src"]` (src layout) or `["."]`, plus the `sdd/config.json`
  `test_command` alternative. It never edits the user's pytest config.
- `install_sdd_integration` appends `note: <sentence>` after the `test_command` warning (not in dry-run).
- Doctor: informational `sdd: worktree tests isolated` check in `_check_sdd`, built from the same helper (lazy
  import, absence-tolerant; `test_command` from `load_sdd_config`).

**NOT in scope**: editing pytest config automatically; non-pytest runners.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | `worktree_test_isolation` + install note |
| `packages/ai-parrot/src/parrot/self_/doctor.py` | MODIFY | `_check_worktree_tests` in `_check_sdd` |
| `packages/ai-parrot/tests/sdd/test_installer.py` | MODIFY | helper + install-note tests |
| `packages/ai-parrot/tests/self_/test_doctor_sdd.py` | MODIFY | informational doctor check test |

---

## Codebase Contract (Anti-Hallucination)

Verified on `feat-FEAT-633-parrot-installer` at `3d66594c6b` (2026-11-03).

```python
# packages/ai-parrot/src/parrot/sdd/installer.py
def install_sdd_integration(...)                                     # line 934 (actions tail ~1022-1030)
def _test_command_warning(config: "SddConfig") -> str | None        # line 842
# packages/ai-parrot/src/parrot/sdd/config.py
def load_sdd_config(root) -> SddConfig   # .test_command: str | None, .base_branch
# packages/ai-parrot/src/parrot/self_/doctor.py
def _check_sdd(root: Path) -> list[DoctorCheck]                      # line 186
```

---

## Acceptance Criteria

- [ ] Python repo, no pytest `pythonpath`, no `test_command` → install prints a `note:` naming `pythonpath`;
      doctor shows an informational (non-failing) `sdd: worktree tests isolated` check.
- [ ] Editable install in `.venv` pointing at the root is named in the note.
- [ ] `pythonpath` configured, a non-pytest `test_command`, or a non-Python repo → no note, doctor check ok.
- [ ] `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_installer.py -q`
- `pytest packages/ai-parrot/tests/self_/test_doctor_sdd.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_test_command_fallback.py -q`

## Agent Instructions

Work in `feat-FEAT-633-parrot-installer`; run tests with `PYTHONPATH=packages/ai-parrot/src`; stage only the files
above; close with `parrot sdd task close TASK-5118 parrot-installer verified`.

---

## Completion Note
**Completed by**: Claude Opus 5.5 (/sdd-fix, sequential)
**Date**: 2026-11-03
**Notes**: Helper returns None for non-Python repos, a non-pytest or PYTHONPATH-setting test_command, or a pytest `pythonpath` in pyproject ([tool.pytest.ini_options] / [tool.pytest]), pytest.ini, tox.ini or setup.cfg [tool:pytest]. Editable detection scans `.venv` dist-info `direct_url.json` (dir_info.editable, file:// URL at or under root). Install note is skipped in dry-run (dry-run returns the plan before notes). Doctor check is informational both ways. 11 new tests; sdd installer + self_ + test_command_fallback 152 passed, other sdd installer/CLI suites 87 passed; ruff clean.
