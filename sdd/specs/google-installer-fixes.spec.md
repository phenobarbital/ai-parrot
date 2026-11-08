---
type: feature
base_branch: dev
feature_id: FEAT-838
projects: [ai-parrot]
tags: [google, installer, launcher, ledger-fix]
discovered_from: issue:e92e5f160cdd
docs:
  policy: none
---

# Feature Specification: Google installer prefers the installed managed launcher

**Feature ID**: FEAT-838
**Date**: 2026-11-07
**Author**: Jesus Lara (spec drafted with Claude via /sdd-fix)
**Status**: approved
**Target version**: next patch

---

## 1. Motivation & Business Requirements

### Problem Statement

Ledger issue `issue:e92e5f160cdd` (bug, minor, found during FEAT-802).

`_global_parrot_command()` (`knowledge/wiki/google/installer.py:186`) picks the `command` for the
USER-GLOBAL `~/.gemini/config/mcp_config.json` toolkit entries in this order:

1. bare `parrot` if `shutil.which("parrot")` resolves under `parrot_home()`;
2. otherwise the `command` of any existing `parrot-*` entry in that file;
3. otherwise this repository's resolved `parrot` binary.

With the repository venv active (mandatory in interactive shells), `.venv/bin` comes before
`~/.parrot/bin` on `PATH`. Rule 1 fails even though the managed launcher is installed, and rule 2
silently inherits whichever repository wrote the global file first. Observed 2026-11-07: after
`parrot sdd install --host google` from ai-parrot, `parrot-bounded-source`, `parrot-memory` and
`parrot-sdd-coder` had portable args but `command=/home/.../fieldsync/.venv/bin/parrot`, and
`parrot self doctor` reported a cross-repo collision for entries this repository had just written.

### Goals

- When the managed launcher is installed on disk, the global entries get bare `parrot`, whatever the
  `PATH` order is. The launcher resolves the repository from the working directory.
- When rule 2 still inherits a command that lives outside this repository, log a warning naming it.

### Non-Goals (explicitly out of scope)

- No change to `parrot/sdd/installer.py::guard_hook_command` or `launcher.managed_launcher_on_path`
  (the issue mentions them as a possible follow-up; they stay PATH-order only).
- No change to `resolve_portable_mode` or to the repo-local plugin config entries.
- No change to the entry shape (`args`) or to portable/baked selection.

---

## 2. Architectural Design

### `_global_parrot_command()` resolution order

1. **Managed launcher on PATH** (unchanged): `shutil.which("parrot")` resolves under `parrot_home()`
   → return `"parrot"`.
1b. **Managed launcher installed** (new): the launcher shim `parrot_home()/"bin"/"parrot"`
   (`parrot.exe` on Windows) exists AND `script_path(parrot_home()/"venv", "parrot")` exists — the
   same two-part rule `self_/doctor.py::_check_entrypoints` uses → return `"parrot"`, whatever the
   `PATH` order. Rule 1 is kept because existing tests (and installs) put only the shim on `PATH`.
2. Existing parrot-shaped `parrot-*` entry whose command is `"parrot"` or an existing file → reuse it
   (unchanged). If the reused command is an absolute path that is not inside `root` (resolved), log a
   `WARNING` on the module logger naming the entry, the command and the workaround
   (`parrot self install` / `--portable`).
3. Fall back to `assets.resolve_binary(root, "parrot")` (unchanged).

Filesystem errors (`OSError`) while probing rule 1 count as "not installed".

---

## 3. Module Breakdown

### Module 1: launcher-on-disk resolution
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py`
- **Responsibility**: new rule 1 and the cross-repo warning in `_global_parrot_command`; docstring updated.

### Module 2: tests
- **Path**: `packages/ai-parrot/tests/knowledge/wiki/test_google_global_command.py` (new)
- **Responsibility**: unit tests for `_global_parrot_command` with an isolated `PARROT_HOME`/`PATH`.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_installed_launcher_shadowed_on_path_returns_bare_parrot` | M1 | shim + managed venv script exist under `PARROT_HOME`, `PATH` holds only a repo `.venv/bin/parrot`, existing global entry points at another repo's binary → `"parrot"` |
| `test_launcher_shim_without_managed_venv_is_not_installed` | M1 | shim exists (not on `PATH`) but managed venv script does not → falls through to rule 2/3 |
| `test_inherits_foreign_command_with_warning` | M1 | no launcher, existing entry points at an existing binary outside `root` → that command is returned and a WARNING naming it is logged |
| `test_inherited_command_inside_root_no_warning` | M1 | no launcher, existing entry's command is inside `root` → returned, no warning |
| `test_falls_back_to_repo_binary` | M1 | no launcher, no existing entries → `assets.resolve_binary(root, "parrot")` |
| existing `test_google_portable.py` | M1 | unchanged and passing |

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/wiki/test_google_global_command.py
- packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py
- packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py
markers: none

### Test Data / Fixtures

Tests set `HOME`, `PARROT_HOME` and `PATH` under `tmp_path` with `monkeypatch` and create fake
executable files; no real launcher is touched.

---

## 5. Acceptance Criteria

- [ ] AC-1 With the managed launcher installed under `PARROT_HOME` (shim + managed venv script), the global
  toolkit command is bare `parrot` even when another `parrot` comes first on `PATH` and an existing entry
  points at another repository's binary.
- [ ] AC-2 A shim that is not on `PATH` and has no managed venv script does not count as installed.
- [ ] AC-3 When rule 2 reuses an absolute command outside `root`, a WARNING naming that command is logged.
- [ ] AC-4 Validation Contract tests pass; `ruff check` clean on the changed files.

---

## 6. Codebase Contract

- `_global_parrot_command(root: Path, existing: dict[str, Any]) -> str` — `knowledge/wiki/google/installer.py:186`;
  called from `reconcile_toolkit_entries` at `installer.py:297`.
- `_is_parrot_toolkit_shape(entry, name) -> bool` — `installer.py:172`.
- module logger: `installer.py` imports `logging` (line 6); check for an existing `logger =` before adding one.
- `parrot.launcher.parrot_home(env=None) -> Path` — `launcher.py:26` (not resolved).
- `parrot.launcher.script_path(venv: Path, name: str, *, os_name=None) -> Path` — `launcher.py:198`.
- Shim location precedent: `self_/doctor.py:129-131` (`parrot_home() / "bin" / (f"{n}.exe" if os.name == "nt" else n)`
  plus `script_path(managed_venv(), n).exists()`).
- `assets.resolve_binary(root, "parrot")` — fallback, unchanged.
- Test fixtures to mirror: `isolated_env` / launcher fixtures in `tests/knowledge/wiki/test_google_portable.py:170-195`.

---

## 7. Implementation Notes & Constraints

- Run tests from the worktree with `PYTHONPATH=packages/ai-parrot/src`.

---

## 8. Open Questions

None.
