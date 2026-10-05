# TASK-4079: parrot self: component install engine (parrot.self_.components)

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4071, TASK-4077
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (engine half) and §2 Overview item 3. `parrot self add <component>`
installs a toolkit template's `requires_pip` into the **managed** venv (`~/.parrot/venv`)
with the bundled, pinned `uv` (`~/.parrot/bin/uv`), then runs the template's
`post_install` argv. `--here` is the only path that installs into a **project** venv
(spec §1 non-goal "no implicit modification of a project's dependencies"; §7 "Explicit
over implicit"). `update` upgrades ai-parrot in the managed venv; `uninstall` removes the
managed runtime only — `~/.parrot` is a live data directory (spec §7).

This task builds the engine (`parrot.self_.components`); the Click group and doctor are
TASK-4080. Home/venv paths come from `parrot.launcher` (TASK-4071); template metadata
from TASK-4077.

---

## Scope

- Create package `parrot.self_` (trailing underscore: `self` is not a usable module
  name in practice and the spec fixes `parrot/self_/`).
- Implement in `parrot/self_/components.py`:
  - `bundled_uv() -> Path`
  - `install_component(name: str, *, venv: Path, here: bool = False) -> list[str]`
  - `update_runtime(version: str | None = None) -> list[str]`
  - `uninstall_runtime(*, yes: bool) -> list[str]`
- Tests with `subprocess.run` mocked (no network, no real uv).

**NOT in scope**: the `parrot self` Click group, `env`, `doctor` (TASK-4080); the
bootstrap scripts that download uv / create `~/.parrot/venv` (M2 tasks); writing host
configs (`parrot toolkits install` does that); a `--purge` of `~/.parrot` data (spec §7:
out of scope for v1).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/self_/__init__.py` | CREATE | Package marker + docstring |
| `packages/ai-parrot/src/parrot/self_/components.py` | CREATE | Install/update/uninstall engine |
| `packages/ai-parrot/tests/self_/__init__.py` | CREATE | Test package marker (repo convention) |
| `packages/ai-parrot/tests/self_/test_components.py` | CREATE | Engine tests (subprocess mocked) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.toolkit_seed import ToolkitTemplate, available_templates, load_template  # verified: packages/ai-parrot/src/parrot/mcp/toolkit_seed.py:27,49,63
# Created by TASK-4071 (dependency) — names fixed by spec §3 M1:
from parrot.launcher import parrot_home, find_project_root, script_path  # TASK-4071: packages/ai-parrot/src/parrot/launcher.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/toolkit_seed.py
def available_templates() -> tuple[str, ...]:          # line 49 — importlib.resources ONLY (package data)
def load_template(name: str) -> ToolkitTemplate:        # line 63 — raises KeyError for unknown names (line 72-73)
class ToolkitTemplate(BaseModel):                       # line 27
    requires_dist: tuple[str, ...] = ()                 # line 34
    # TASK-4077 adds: requires_pip, post_install, requires_env (tuple[str, ...] = ())

# parrot.launcher (TASK-4071; spec §3 M1 skeleton)
def parrot_home() -> Path: ...                          # $PARROT_HOME or ~/.parrot
def find_project_root(argv: Sequence[str], env: Mapping[str, str], cwd: Path) -> Path | None: ...
def script_path(venv: Path, name: str) -> Path: ...     # venv/bin/name (POSIX); venv/Scripts/name.exe (Windows)
```
- `~/.parrot` live data that must never be removed (spec §7): `wikis.json`, `library/`,
  `skills/`, `brains/`, `parrot.db`, `services/`, `cli/`.
- `.venv/pyvenv.cfg` written by uv carries `uv = 0.11.28` and `version_info = 3.12.3`
  (verified in the repo's own `.venv/pyvenv.cfg`).

### Does NOT Exist
- ~~`parrot.self_` / `parrot/self_/`~~ — created here (and TASK-4080).
- ~~`parrot.launcher`~~ before TASK-4071 lands — do not start until it is `done`.
- ~~any uv download/bootstrap code in core~~ — the pinned uv is placed in `~/.parrot/bin` by `install-parrot.sh/.ps1 --global` (M2), never by this module.
- ~~a repo-local or user-writable template source~~ — `post_install` argv is trusted only because it comes from package data (spec §3 M4, §7).
- ~~an installed-components state file~~ — none; do not invent one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/self_/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/self_/components.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/self_/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/self_/test_components.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#ToolkitTemplate",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#load_template",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#available_templates"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# argv list, no shell, check=True — every subprocess in this module
subprocess.run([str(uv), "pip", "install", "--python", str(python), *requirements], check=True)
```

### Key Constraints
- **Synchronous `subprocess.run` is correct here**: this module is only reached from the
  `parrot self` Click commands (a one-shot CLI process with no event loop), never from an
  aiohttp request path or an agent tool — the async-first rule targets I/O inside
  `async def`; there is none here. Do not wrap it in `asyncio`.
- Never `shell=True`; argv lists only. `post_install` argv comes exclusively from
  packaged templates (spec §7 "`post_install` execution surface").
- Leading `python` token in `post_install` → replaced by the TARGET venv's interpreter
  (`script_path(venv, "python")`), so `python -m playwright install chromium` runs in the
  venv that just received Playwright, not whatever `python` is on PATH.
- `here=False` must target the managed venv only: reject any other `venv` with
  `ValueError` — the engine enforces the spec constraint, not just the CLI.
- `uninstall_runtime` deletes ONLY `bin/`, `venv/`, `python/` directly under
  `parrot_home()`; refuse symlink escape (resolve and check parent).
- Log with `logger = logging.getLogger(__name__)`; return the human-readable action log
  (the CLI echoes it). No `print`.

### References in Codebase
- `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py:49-106` — template loading
- `scripts/install/install-parrot.sh` — the existing project-mode installer (context only)

---

## Implementation Blueprint

### Steps (in order)
1. Create `parrot/self_/__init__.py` (docstring only, no imports) — *why*: keep `parrot self --help` cheap; LazyGroup imports `parrot.self_.cli` (TASK-4080).
2. Implement `bundled_uv()` and `_venv_python()` — *why*: single place that knows the home layout and Windows names (`script_path`).
3. Implement `install_component` (resolve template → pip install → post_install) — *why*: spec §3 M3 skeleton.
4. Implement `update_runtime` / `uninstall_runtime` — *why*: spec §2 item 3 lifecycle.
5. Write tests with `subprocess.run` mocked and a fake `PARROT_HOME` — *why*: no network / real uv in CI.

### `packages/ai-parrot/src/parrot/self_/__init__.py` (CREATE)
```python
"""`parrot self` — manage the parrot-managed runtime under ``~/.parrot`` (FEAT-633).

Submodules: :mod:`parrot.self_.components` (install/update/uninstall engine),
:mod:`parrot.self_.doctor` and :mod:`parrot.self_.cli` (TASK-4080). The package name
carries a trailing underscore; the CLI command is ``parrot self``.
"""
```

### `packages/ai-parrot/src/parrot/self_/components.py` (CREATE)
```python
"""Component install engine for ``parrot self`` (FEAT-633, spec §3 M3).

Synchronous by design: only the one-shot ``parrot self`` CLI calls this module.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from parrot.launcher import find_project_root, parrot_home, script_path  # TASK-4071
from parrot.mcp.toolkit_seed import load_template  # verified: mcp/toolkit_seed.py:63

logger = logging.getLogger(__name__)

#: Only these children of ``parrot_home()`` belong to the runtime (spec §7).
RUNTIME_DIRS: tuple[str, ...] = ("bin", "venv", "python")
#: Distribution upgraded by ``update_runtime``.
CORE_DIST: str = "ai-parrot"


def managed_venv() -> Path:
    """Return ``parrot_home()/'venv'`` (the managed venv)."""
    return parrot_home() / "venv"


def bundled_uv() -> Path:
    """Return the pinned uv placed by the ``--global`` bootstrap.

    ``parrot_home()/'bin'/'uv'`` (``uv.exe`` on Windows). Falls back to ``shutil.which('uv')``
    with a logged warning so dev setups without the bootstrap still work.

    Raises:
        FileNotFoundError: neither the bundled uv nor a PATH uv exists.
    """
    bundled = parrot_home() / "bin" / ("uv.exe" if os.name == "nt" else "uv")
    if bundled.is_file():
        return bundled
    found = shutil.which("uv")
    if found:
        logger.warning("bundled uv missing at %s; falling back to %s", bundled, found)
        return Path(found)
    raise FileNotFoundError(f"uv not found at {bundled} nor on PATH — run install-parrot --global")


def _venv_python(venv: Path) -> Path:
    """Interpreter of ``venv`` (``bin/python`` or ``Scripts\\python.exe``)."""
    python = script_path(venv, "python")
    if not python.exists():
        raise FileNotFoundError(f"no interpreter in venv {venv} (expected {python})")
    return python


def _project_venv() -> Path:
    """The project venv ``--here`` targets: ``<project root>/.venv``.

    Raises:
        FileNotFoundError: no project root, or the root has no ``.venv``.
    """
    root = find_project_root(sys.argv[1:], os.environ, Path.cwd())
    # FILL IN: root None → FileNotFoundError naming cwd; candidate = root/'.venv' (the worktree's own
    # venv when cwd is a linked worktree — find_project_root returns the worktree root); must contain a
    # python (via _venv_python) — bounded by spec §5 "`--here` targets the project venv"
    raise NotImplementedError


def _run(argv: list[str], log: list[str]) -> None:
    """Run one argv (no shell, check=True) and record it in ``log``."""
    logger.info("running: %s", argv)
    log.append("$ " + " ".join(argv))
    subprocess.run(argv, check=True)


def install_component(name: str, *, venv: Path, here: bool = False) -> list[str]:
    """Install toolkit template ``name``'s ``requires_pip`` and run its ``post_install``.

    Args:
        name: Packaged toolkit template name (``available_templates()``).
        venv: Target venv when ``here`` is False — MUST be the managed venv.
        here: Target the project venv instead (the only path into a project).

    Returns:
        Human-readable action log.

    Raises:
        KeyError: unknown template.
        ValueError: ``here`` is False and ``venv`` is not the managed venv.
        FileNotFoundError: no uv, or the target venv has no interpreter.
        subprocess.CalledProcessError: uv or post_install failed.
    """
    template = load_template(name)
    target = _project_venv() if here else Path(venv)
    if not here and target.resolve() != managed_venv().resolve():
        raise ValueError(f"refusing to install into {target}: use --here for a project venv")
    python = _venv_python(target)
    log: list[str] = [f"target venv: {target} ({'project' if here else 'managed'})"]
    if not template.requires_pip:
        log.append(f"{name}: nothing to install (core-only toolkit)")
        return log
    _run([str(bundled_uv()), "pip", "install", "--python", str(python), *template.requires_pip], log)
    if template.post_install:
        argv = list(template.post_install)
        if argv[0] == "python":
            argv[0] = str(python)  # leading `python` placeholder = target venv interpreter (TASK-4077 contract)
        _run(argv, log)
    log.append(f"{name}: installed — now run `parrot toolkits install {name}` to expose it")
    return log


def update_runtime(version: str | None = None) -> list[str]:
    """Upgrade ai-parrot in the managed venv (``==version`` when given)."""
    python = _venv_python(managed_venv())
    requirement = f"{CORE_DIST}=={version}" if version else CORE_DIST
    log: list[str] = []
    # FILL IN: whether to re-pass extras installed by the bootstrap (`--with`) — no state file exists,
    # and uv keeps already-installed packages, so the default is a plain `--upgrade <requirement>`;
    # bounded by spec §1 non-goal (no new state) and §7
    _run([str(bundled_uv()), "pip", "install", "--python", str(python), "--upgrade", requirement], log)
    return log


def uninstall_runtime(*, yes: bool) -> list[str]:
    """Remove the managed runtime (``bin/``, ``venv/``, ``python/``) — never user data.

    Raises:
        PermissionError: ``yes`` is False (the CLI confirms before calling with ``yes=True``).
    """
    if not yes:
        raise PermissionError("uninstall requires explicit confirmation (--yes)")
    home = parrot_home().resolve()
    log: list[str] = []
    for child in RUNTIME_DIRS:
        path = home / child
        # FILL IN: skip absent; a symlink → unlink only (never follow); a real dir → assert
        # path.resolve().parent == home then shutil.rmtree; on Windows the running interpreter inside
        # venv/ cannot be deleted — catch PermissionError/OSError and log the manual removal command
        # instead of failing half-way — bounded by spec §7 "may only touch bin/ and venv/" (+ python/)
        raise NotImplementedError
    log.append(f"kept user data in {home} (wikis, library, skills, brains, parrot.db, services)")
    return log
```
**Why this shape**: the `here`/managed check lives in the engine so no caller can install
into a project implicitly (spec §5). `bundled_uv()`'s PATH fallback is for dev setups only
and is always logged.

### `packages/ai-parrot/tests/self_/__init__.py` (CREATE)
```python
```

### `packages/ai-parrot/tests/self_/test_components.py` (CREATE)
```python
"""`parrot.self_.components` (FEAT-633, TASK-4079). subprocess.run is always mocked."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from parrot.self_ import components


@pytest.fixture
def fake_managed_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """~/.parrot-like tree: bin/uv + venv with an interpreter stub + live data; sets PARROT_HOME."""
    home = tmp_path / "parrot-home"
    bindir = "Scripts" if os.name == "nt" else "bin"
    exe = ".exe" if os.name == "nt" else ""
    (home / "bin").mkdir(parents=True)
    (home / "bin" / f"uv{exe}").write_text("", encoding="utf-8")
    (home / "venv" / bindir).mkdir(parents=True)
    (home / "venv" / bindir / f"python{exe}").write_text("", encoding="utf-8")
    (home / "wikis.json").write_text("{}", encoding="utf-8")
    (home / "library").mkdir()
    monkeypatch.setenv("PARROT_HOME", str(home))
    return home


def test_install_component_managed(fake_managed_home: Path) -> None:
    """requires_pip goes to `uv pip install --python <managed python>`; post_install's python is substituted."""
    with mock.patch.object(components.subprocess, "run") as run:
        log = components.install_component("scraping", venv=fake_managed_home / "venv")
    first, second = (call.args[0] for call in run.call_args_list)
    assert first[1:4] == ["pip", "install", "--python"] and first[-1] == "ai-parrot-tools[scraping]"
    assert second[0] == first[4]  # the venv interpreter, not a bare "python"
    assert second[1:] == ["-m", "playwright", "install", "chromium"]
    assert log


def test_install_rejects_non_managed_venv_without_here(fake_managed_home: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="--here"):
        components.install_component("scraping", venv=tmp_path / "other-venv")


def test_install_here_targets_project_venv(fake_managed_home: Path, tmp_path: Path, monkeypatch) -> None:
    # FILL IN: make a tmp repo (`.git` dir + `.venv` with python stub), chdir into it, patch
    # components.find_project_root to return it; assert `--python` points into <repo>/.venv — bounded by spec §5
    raise NotImplementedError


def test_core_only_template_installs_nothing(fake_managed_home: Path) -> None:
    with mock.patch.object(components.subprocess, "run") as run:
        components.install_component("memory", venv=fake_managed_home / "venv")
    run.assert_not_called()


def test_unknown_component_raises_keyerror(fake_managed_home: Path) -> None:
    with pytest.raises(KeyError):
        components.install_component("no-such-toolkit", venv=fake_managed_home / "venv")


def test_bundled_uv_falls_back_to_path_with_warning(tmp_path: Path, monkeypatch, caplog) -> None:
    # FILL IN: PARROT_HOME without bin/uv; patch components.shutil.which → "/usr/bin/uv"; assert path + warning logged
    raise NotImplementedError


def test_update_runtime_pins_version(fake_managed_home: Path) -> None:
    with mock.patch.object(components.subprocess, "run") as run:
        components.update_runtime("9.9.9")
    assert run.call_args.args[0][-1] == "ai-parrot==9.9.9"


def test_uninstall_keeps_user_data(fake_managed_home: Path) -> None:
    components.uninstall_runtime(yes=True)
    assert not (fake_managed_home / "venv").exists() and not (fake_managed_home / "bin").exists()
    assert (fake_managed_home / "wikis.json").exists() and (fake_managed_home / "library").is_dir()


def test_uninstall_requires_yes(fake_managed_home: Path) -> None:
    with pytest.raises(PermissionError):
        components.uninstall_runtime(yes=False)
```
**Why this shape**: the fixture is the spec §4 `fake_managed_home` fixture; every subprocess
call is mocked, so the tests prove argv shape without network or a real uv.

### FILL IN checklist
- [ ] `components.py::_project_venv` — root/venv resolution + errors; bounded by spec §5 `--here`
- [ ] `components.py::update_runtime` — extras policy; bounded by spec §1 (no state file)
- [ ] `components.py::uninstall_runtime` — per-dir removal, symlink + Windows handling; bounded by spec §7
- [ ] `test_components.py::test_install_here_targets_project_venv` — bounded by spec §5
- [ ] `test_components.py::test_bundled_uv_falls_back_to_path_with_warning` — bounded by brief (logged fallback)

---

## Acceptance Criteria

- [ ] `install_component(name, venv=<managed>)` runs `<bundled uv> pip install --python <managed python> <requires_pip...>` then `post_install` with `python` replaced by the target interpreter (spec §5 "`parrot self add <component>` installs into the managed venv and runs post-install").
- [ ] `here=True` targets the project venv; `here=False` with any non-managed `venv` raises `ValueError` (spec §5 "`--here` … is the only way dependencies enter a project").
- [ ] Core-only templates (empty `requires_pip`) run no subprocess.
- [ ] `bundled_uv()` prefers `~/.parrot/bin/uv[.exe]`, falls back to PATH with a logged warning, else `FileNotFoundError`.
- [ ] `uninstall_runtime(yes=True)` removes only `bin/`, `venv/`, `python/`; user data survives (spec §7).
- [ ] No `shell=True`, no `print`; `ruff check packages/ai-parrot/src/parrot/self_/` clean.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/self_/test_components.py -q`

---

## Test Specification

See the CREATE block for `packages/ai-parrot/tests/self_/test_components.py` (managed
install argv, `--here`, managed-only guard, core-only no-op, unknown name, uv fallback,
update pin, uninstall data safety).

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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4079 parrot-installer verified`
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
