# TASK-4071: Launcher core: stdlib venv resolution (parrot.launcher)

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (resolution half). The three console scripts (`parrot`, `wikitoolkit`,
`bookstore`) will enter through a stdlib-only launcher that, ONLY when running from the
managed venv (`$PARROT_HOME/venv`), resolves a better venv at launch time:
`PARROT_VENV` → project venv (worktree `.venv` first, then the main checkout's) →
`VIRTUAL_ENV` → stay managed (spec §2 Overview item 2, §5 AC1-AC2).

This task creates `parrot/launcher.py` with the constants and the pure resolution functions.
It is also the single home-path authority (`parrot_home`) that TASK-4073 consolidates onto,
and `script_path` is the Windows-aware binary resolver TASK-4081/4083/4084 use.

**Hard rule (spec §3 M1, §7)**: the launcher is **stdlib-only forever** — it runs before every
hook invocation (FEAT-595 latency). `parrot/__init__.py` imports only stdlib + `parrot.version`,
so `import parrot.launcher` stays cheap.

---

## Scope

- Create `packages/ai-parrot/src/parrot/launcher.py` with constants `PARROT_HOME_ENV`,
  `PARROT_VENV_ENV`, `PARROT_PROJECT_ENV`, `LOOP_GUARD_ENV`, `MANAGED_PYTHON` and functions
  `parrot_home`, `is_managed`, `repository_paths`, `find_project_root`, `script_path`,
  `resolve_venv`.
- Port (do NOT import) `repository_paths` and its `existing_directory` helper from
  `flows/dev_loop/worktree_environment.py`.
- Implement warn-once-per-process stderr warnings for a project venv lacking the script.
- Create `packages/ai-parrot/tests/launcher/__init__.py` (this task owns the new test dir) and
  unit tests for every spec §4 M1 row except the subprocess ones.

**NOT in scope**: `reexec`, `main_parrot`/`main_wikitoolkit`/`main_bookstore`, the
`[project.scripts]` repoint, the stdlib-only import test and the subprocess state machine
(all TASK-4072); delegating the three existing `parrot_home()` copies (TASK-4073); host
emitters (TASK-4081+).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/launcher.py` | CREATE | Constants + pure venv-resolution functions (stdlib only) |
| `packages/ai-parrot/tests/launcher/__init__.py` | CREATE | New test package marker (repo convention) |
| `packages/ai-parrot/tests/launcher/test_launcher_core.py` | CREATE | Unit tests: home, managed check, worktree, order/validity, Windows path, warn-once |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Stdlib ONLY. No parrot.* import, no third-party import — not even typing_extensions.
import os, sys                                   # stdlib
from collections.abc import Mapping, Sequence    # stdlib
from pathlib import Path                         # stdlib
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py — PORT SOURCE (copy logic, never import:
#   importing parrot.flows.* would break the stdlib-only rule)
def existing_directory(path: Path) -> Path:                     # line 27 — nearest existing ancestor, resolved
def repository_paths(cwd: Path) -> tuple[Path, Path | None]:    # lines 53-71
#   walks cwd + parents; `.git` dir → (root, marker.resolve()); `.git` FILE → must start "gitdir: "
#   (else raises ValueError, line 63); git_dir = abspath(root / gitdir); if git_dir/"commondir" is a file,
#   git_dir = abspath(git_dir / commondir); returns (root, git_dir.resolve() if git_dir.is_dir() else None);
#   no marker → (cwd, None) (line 71)
def shared_environments(cwd: Path) -> tuple[Path, ...]:         # lines 74-92 — shows the main-checkout venv is
#   `git_dir.parent / ".venv"` (line 79) and validity = `(resolved / "pyvenv.cfg").is_file()` (line 86)

# The three existing PARROT_HOME readers — semantics parrot_home() MUST reproduce exactly:
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1223-1235
#   raw = os.environ.get("PARROT_HOME") or f"~/{PARROT_DIR}"   (line 1234; PARROT_DIR = ".parrot", line 44)
#   return Path(raw).expanduser()                               — read per call, never cached; NO .resolve()
# packages/ai-parrot/src/parrot/knowledge/bookstore/config.py:66-75  — same, literal "~/.parrot" (line 74)
# packages/ai-parrot/src/parrot/cli/modes.py:68-74                   — same, literal "~/.parrot" (line 70)
#   ⇒ empty-string PARROT_HOME falls back to the default (`or`), `~` is expanded, path is NOT resolved.

# Existing CLI options named --project (collision hazard for argv parsing, see Implementation Notes):
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:3907  @click.option("--project", ...)  (entity attribute)
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:2734, :5496  (other subcommand --project options)
```

### Does NOT Exist
- ~~`parrot/launcher.py`, `PARROT_VENV`, `PARROT_PROJECT`, `PARROT_LAUNCHER_RESOLVED`~~ — all new here (spec §6).
- ~~`parrot.launcher.reexec` / `main_*`~~ — TASK-4072 adds them; do not stub them here.
- ~~Windows venv handling (`Scripts\`, `.exe`) anywhere in the repo~~ — `script_path` is the first.
- ~~`packages/ai-parrot/tests/launcher/`~~ — new dir, created by this task.
- ~~`parrot.knowledge.wiki.project.find_project_root` as a reusable launcher helper~~ — it exists
  (project.py:920) but looks for `.parrot/wiki.json` and lives behind pydantic imports; the launcher's
  `find_project_root` is a different, stdlib function with a different signature. Never import it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/launcher.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/launcher/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/launcher/test_launcher_core.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#existing_directory",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#repository_paths",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#shared_environments",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#parrot_home",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/config.py#_parrot_home",
    "sym:packages/ai-parrot/src/parrot/cli/modes.py#cli_state_dir"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`flows/dev_loop/worktree_environment.py` is the precedent for a stdlib-only module that
"can run directly as a Claude hook" (its module docstring, lines 1-5). Copy its
`repository_paths` loop verbatim in spirit, with ONE deliberate change: a malformed `.git`
file must NOT raise — a launcher crash would take down every console script, so treat it as
"no repository" (return `(cwd, None)`).

### Key Constraints
- **Pure functions**: everything takes `env`/`argv`/`cwd` parameters; nothing but `parrot_home()`
  with `env=None` and `is_managed()` with `prefix=None` reads process state — tests never
  monkeypatch `os.environ`.
- `parrot_home(env=None)` keeps the spec signature callable as `parrot_home()` and reads
  `os.environ` on EVERY call (existing test `test_parrot_home_env_is_read_per_call` relies on it).
- **Validity** of a candidate venv: `pyvenv.cfg` is a file AND `script_path(venv, script)` exists.
- **Never resolve to the managed venv as a "project"/"VIRTUAL_ENV" candidate** — compare
  realpaths and skip it; otherwise TASK-4072 would re-exec into itself.
- **Symlinks**: compare `os.path.realpath` of both sides in `is_managed` and the self-skip above
  (a symlinked interpreter/venv must still count as managed — spec §4 integration row).
- **`--project` collision**: wikitoolkit subcommands already define `--project` options with
  other meanings (cli.py:2734, 3907, 5496). `find_project_root` therefore honours `--project`
  ONLY in leading position (`argv[0] == "--project"` with `argv[1]`, or `argv[0]` starting with
  `--project=`), i.e. before any subcommand. TASK-4072 strips it before dispatching.
- **Warnings**: `sys.stderr.write` only (never stdout — spec §5 AC4); at most once per process per
  kind via a module-level set; message names the venv and the script and says what was used instead.
- `script_path(venv, name, *, os_name=None)`: build with `venv / ...` only — never `Path(str)`
  inside a patched `os.name == "nt"` window (pathlib would instantiate `WindowsPath` on POSIX).
- No `logging` — the module must not configure or emit through logging handlers (they may point
  at stdout in host processes).

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py` — port source
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1223` — PARROT_HOME semantics

---

## Implementation Blueprint

### Steps (in order)
1. Write constants + `parrot_home` + `is_managed` — *why*: every other function and TASK-4073 depend on them.
2. Port `_existing_directory` + `repository_paths` — *why*: worktree-first ordering needs the main checkout.
3. Write `find_project_root` and `script_path` — *why*: candidate discovery inputs.
4. Write `resolve_venv` with the fixed rule names — *why*: TASK-4072 and `parrot self env` (TASK-4080) consume `(venv, rule)`.
5. Write `tests/launcher/__init__.py` (empty) and the unit tests — *why*: spec §4 M1 rows.

### `packages/ai-parrot/src/parrot/launcher.py` (CREATE)
```python
"""Stdlib-only launch-time venv resolution for parrot console scripts (FEAT-633 M1).

HARD RULE: import nothing but the standard library here — this module fronts every
``wikitoolkit claude-hook`` call. Enforced by tests/launcher/test_launcher_stdlib_only.py (TASK-4072).
"""
from __future__ import annotations

import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

PARROT_HOME_ENV = "PARROT_HOME"            # existing convention: knowledge/wiki/project.py:1234
PARROT_VENV_ENV = "PARROT_VENV"            # new explicit override
PARROT_PROJECT_ENV = "PARROT_PROJECT"      # new project-root pin
LOOP_GUARD_ENV = "PARROT_LAUNCHER_RESOLVED"
MANAGED_PYTHON = "3.12"                    # owner decision (spec §8)
_DEFAULT_HOME = "~/.parrot"
_WARNED: set[str] = set()                  # warn-once-per-process registry (keys: "project:<venv>", "PARROT_VENV")


def parrot_home(env: Mapping[str, str] | None = None) -> Path:
    """``$PARROT_HOME`` or ``~/.parrot``, ``~``-expanded, NOT resolved; read on every call."""
    source = os.environ if env is None else env
    return Path(source.get(PARROT_HOME_ENV) or _DEFAULT_HOME).expanduser()


def is_managed(prefix: str | None = None, *, env: Mapping[str, str] | None = None) -> bool:
    """True iff ``prefix`` (default ``sys.prefix``) is inside ``parrot_home()/'venv'`` (realpaths)."""
    managed = os.path.realpath(parrot_home(env) / "venv")
    current = os.path.realpath(prefix if prefix is not None else sys.prefix)
    return current == managed or current.startswith(managed + os.sep)


def _existing_directory(path: Path) -> Path:
    """Port of worktree_environment.existing_directory (:27): nearest existing ancestor, resolved."""
    # FILL IN: copy the body from worktree_environment.py:46-50 — bounded by stdlib-only
    raise NotImplementedError


def repository_paths(cwd: Path) -> tuple[Path, Path | None]:
    """(repo_root, common_git_dir_or_None). Port of worktree_environment.py:53-71.

    Deviation: a malformed ``.git`` file yields ``(cwd, None)`` instead of raising.
    The main checkout of a linked worktree is ``common_git_dir.parent``.
    """
    # FILL IN: port lines 55-71 (gitdir:/commondir parsing, pruned admin dir → None) — bounded by
    #   the deviation above and spec §4 test_worktree_prefers_local_then_main
    raise NotImplementedError


def find_project_root(argv: Sequence[str], env: Mapping[str, str], cwd: Path) -> Path | None:
    """Leading ``--project <p>``/``--project=<p>`` → PARROT_PROJECT → CLAUDE_PROJECT_DIR → walk-up to ``.git``."""
    # FILL IN: leading-position --project only (collision with wiki subcommand --project options,
    #   wiki/cli.py:2734,3907,5496); relative values resolve against cwd; a pinned root that does
    #   not exist falls through to the next source; walk-up accepts `.git` dir OR file — bounded by AC-3
    raise NotImplementedError


def script_path(venv: Path, name: str, *, os_name: str | None = None) -> Path:
    """``venv/bin/<name>`` on POSIX; ``venv/Scripts/<name>.exe`` on Windows."""
    if (os_name or os.name) == "nt":
        return venv / "Scripts" / f"{name}.exe"
    return venv / "bin" / name


def _warn_once(key: str, message: str) -> None:
    """Write ``message`` to stderr at most once per process for ``key``."""
    if key in _WARNED:
        return
    _WARNED.add(key)
    sys.stderr.write(f"parrot: {message}\n")


def resolve_venv(script: str, *, argv: Sequence[str], env: Mapping[str, str], cwd: Path) -> tuple[Path, str]:
    """Return ``(venv, rule)``; rule ∈ {'PARROT_VENV','project','VIRTUAL_ENV','managed'}.

    A candidate is valid iff it has ``pyvenv.cfg`` and ``script_path(venv, script)`` exists and it
    is not the managed venv itself. A project ``.venv`` lacking the script warns once (stderr) and
    is skipped. Never raises: any OSError while probing a candidate skips that candidate.
    """
    managed = parrot_home(env) / "venv"
    # FILL IN: ordered candidates — (env[PARROT_VENV], 'PARROT_VENV');
    #   project: root = find_project_root(...); (root/.venv, 'project'), then if repository_paths(root)[1]
    #   is not None and its parent != root: (common.parent/.venv, 'project');
    #   (env[VIRTUAL_ENV], 'VIRTUAL_ENV'). Return first valid; else (managed, 'managed').
    #   Invalid PARROT_VENV also warns once (explicit setting silently ignored is worse).
    #   — bounded by spec §5 AC2 and the rule names fixed above
    raise NotImplementedError
```
**Why this shape**: names/constants are fixed by spec §3 M1 and the shared brief; `env=`/`os_name=`
keywords keep `parrot_home()` / `script_path(venv, name)` call-compatible with the spec skeleton
while making tests pure. `_WARNED` is a set so the project warning and the PARROT_VENV warning are
each emitted once (the spec's "one stderr warning per process").

### `packages/ai-parrot/tests/launcher/__init__.py` (CREATE)
```python
```
**Why**: empty package marker — new test dirs need `__init__.py` (repo convention; `tests/cli/__init__.py` precedent).

### `packages/ai-parrot/tests/launcher/test_launcher_core.py` (CREATE)
```python
"""Unit tests for parrot.launcher resolution (FEAT-633 M1, TASK-4071)."""
from __future__ import annotations

from pathlib import Path

import pytest

from parrot import launcher  # created by this task


def make_venv(path: Path, *scripts: str) -> Path:
    """Fake venv: pyvenv.cfg + empty POSIX script stubs."""
    (path / "bin").mkdir(parents=True)
    (path / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    for name in scripts:
        (path / "bin" / name).write_text("#!/bin/sh\n", encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _reset_warnings(monkeypatch):
    monkeypatch.setattr(launcher, "_WARNED", set())


@pytest.fixture
def linked_worktree_repo(tmp_path: Path) -> tuple[Path, Path]:
    """main checkout (real .git dir) + linked worktree (.git FILE with gitdir:, admin dir with commondir)."""
    main = tmp_path / "main"
    admin = main / ".git" / "worktrees" / "wt"
    admin.mkdir(parents=True)
    (admin / "commondir").write_text("../..\n", encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {admin}\n", encoding="utf-8")
    return main, wt


def test_parrot_home_env_default_and_tilde(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert launcher.parrot_home({}) == tmp_path / ".parrot"
    assert launcher.parrot_home({"PARROT_HOME": ""}) == tmp_path / ".parrot"
    assert launcher.parrot_home({"PARROT_HOME": "~/x"}) == tmp_path / "x"


def test_launcher_not_managed(tmp_path):
    env = {"PARROT_HOME": str(tmp_path / "home")}
    assert launcher.is_managed(str(tmp_path / "other"), env=env) is False
    assert launcher.is_managed(str(tmp_path / "home" / "venv"), env=env) is True


def test_resolve_order_and_validity(tmp_path):
    home, proj = tmp_path / "home", tmp_path / "proj"
    make_venv(home / "venv", "wikitoolkit")
    (proj / ".git").mkdir(parents=True)
    make_venv(proj / ".venv", "wikitoolkit")
    explicit = make_venv(tmp_path / "explicit", "wikitoolkit")
    ve = make_venv(tmp_path / "ve", "wikitoolkit")
    env = {"PARROT_HOME": str(home), "PARROT_VENV": str(explicit), "VIRTUAL_ENV": str(ve)}
    assert launcher.resolve_venv("wikitoolkit", argv=[], env=env, cwd=proj)[1] == "PARROT_VENV"
    env.pop("PARROT_VENV")
    assert launcher.resolve_venv("wikitoolkit", argv=[], env=env, cwd=proj) == (proj / ".venv", "project")
    # FILL IN: project venv without the script ⇒ VIRTUAL_ENV; nothing valid ⇒ (home/venv, 'managed')


def test_worktree_prefers_local_then_main(linked_worktree_repo, tmp_path):
    main, wt = linked_worktree_repo
    make_venv(main / ".venv", "parrot")
    env = {"PARROT_HOME": str(tmp_path / "home")}
    assert launcher.resolve_venv("parrot", argv=[], env=env, cwd=wt)[0].resolve() == (main / ".venv").resolve()
    make_venv(wt / ".venv", "parrot")
    assert launcher.resolve_venv("parrot", argv=[], env=env, cwd=wt)[0] == wt / ".venv"


def test_script_path_windows(tmp_path):
    assert launcher.script_path(tmp_path, "bookstore", os_name="nt").parts[-2:] == ("Scripts", "bookstore.exe")
    assert launcher.script_path(tmp_path, "bookstore", os_name="posix") == tmp_path / "bin" / "bookstore"


def test_warn_once_per_session(tmp_path, capsys):
    proj = tmp_path / "proj"
    (proj / ".git").mkdir(parents=True)
    make_venv(proj / ".venv")                      # venv WITHOUT the script
    env = {"PARROT_HOME": str(tmp_path / "home")}
    for _ in range(3):
        launcher.resolve_venv("wikitoolkit", argv=[], env=env, cwd=proj)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("\n") == 1


# FILL IN: find_project_root precedence (leading --project / --project= > PARROT_PROJECT >
#   CLAUDE_PROJECT_DIR > walk-up), non-leading --project ignored, malformed .git file → no crash,
#   managed venv never returned as 'VIRTUAL_ENV' — bounded by spec §4 M1 rows
```

### FILL IN checklist
- [ ] `launcher.py::_existing_directory` / `repository_paths` — faithful port + no-raise deviation; bounded by worktree_environment.py:27-71
- [ ] `launcher.py::find_project_root` — leading-only `--project`, precedence, existence checks; bounded by AC-3
- [ ] `launcher.py::resolve_venv` — candidate order, validity, self-skip, warn-once; bounded by spec §5 AC2
- [ ] `test_launcher_core.py` — remaining cases listed in the trailing FILL IN

---

## Acceptance Criteria

- [ ] AC-1: `parrot.launcher` exposes exactly the spec §3 M1 constants and `parrot_home`, `is_managed`, `repository_paths`, `find_project_root`, `script_path`, `resolve_venv`; imports only the stdlib (visual check here; enforced by TASK-4072's test).
- [ ] AC-2: `resolve_venv` order is `PARROT_VENV` → project venv (worktree `.venv` first, then main checkout) → `VIRTUAL_ENV` → managed; candidates without the requested script are skipped; rule strings are exactly `'PARROT_VENV'`, `'project'`, `'VIRTUAL_ENV'`, `'managed'` (spec §5 AC2).
- [ ] AC-3: `find_project_root` precedence: leading `--project` → `PARROT_PROJECT` → `CLAUDE_PROJECT_DIR` → cwd walk-up to a `.git` dir or file; a non-leading `--project` is ignored.
- [ ] AC-4: a project venv lacking the script warns exactly once per process on stderr and nothing is written to stdout (spec §5 AC2, AC4).
- [ ] AC-5: `parrot_home()` matches today's three copies exactly: env read per call, empty value → `~/.parrot`, `~` expanded, not resolved.
- [ ] AC-6: `script_path` returns `Scripts/<name>.exe` for Windows and `bin/<name>` otherwise (spec §5 Windows AC).
- [ ] AC-7: a malformed `.git` file never raises out of any launcher function.
- [ ] `ruff check packages/ai-parrot/src/parrot/launcher.py packages/ai-parrot/tests/launcher/` passes.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/launcher/test_launcher_core.py -q`

---

## Test Specification

The `test_launcher_core.py` blueprint block above is the scaffold (spec §4 rows
`test_launcher_not_managed_direct_call` (pure half), `test_resolve_order_and_validity`,
`test_worktree_prefers_local_then_main`, `test_script_path_windows`,
`test_warn_once_per_session`; fixture `linked_worktree_repo` per spec §4 Test Data). Fake venvs
are `pyvenv.cfg` + script stubs in `tmp_path`; no subprocess, no real git.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug parrot-installer --feature-id FEAT-633`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/parrot-installer.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/parrot-installer.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4071 parrot-installer verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
