# HOTFIX-installer-uv-shadowing-1: Bounded uv resolver, `libexec` layout and legacy migration in the Python runtime

**Feature**: installer-uv-shadowing (the `--global` installer's pinned uv shadows the user's uv on PATH)
**Spec**: `sdd/briefs/installer-uv-shadowing.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The runtime finds uv only at `~/.parrot/bin/uv` (`components.py:164`), and the doctor demands exactly that file at
exactly `0.11.28` (`doctor.py:67`). This task moves the runtime to the agreed model (brief decisions 1, 2, 5, 6):

- a compatible range `>=0.11.28,<0.12`;
- a private `~/.parrot/libexec/` holding either the pinned uv or `uv-path`, the recorded path of the user's
  compatible uv;
- one resolver used by `parrot self add`, `parrot self update` and `parrot self doctor`;
- migration off the legacy `bin/uv`, run by `parrot self update`.

The installers (tasks 2 and 3) write the same layout and test that their constants match this module's.

---

## Scope

- Create `parrot/self_/uv.py`. It holds the range and pin constants, version parsing and probing, the PATH search
  that skips `$PARROT_HOME/bin` and `libexec`, the `uv-path` read and write, `resolve_uv()` and
  `migrate_legacy_uv()`.
- Make `components.bundled_uv()` delegate to `resolve_uv()`. Add `"libexec"` to `RUNTIME_DIRS`. Call
  `migrate_legacy_uv()` at the start of `update_runtime()`, with its lines first in the returned log.
- Doctor: base `_check_uv()` on `resolve_uv()`. Add an informational `_check_uv_layout()` that reports legacy
  `bin/uv` / `bin/uvx`. Run it right after `_check_uv()` in `run_doctor`. Import `PINNED_UV_VERSION` from `uv.py`
  so `doctor.PINNED_UV_VERSION` still imports.
- Tests: a new `tests/self_/test_uv.py`; update `tests/self_/test_components.py` (fixture layout, the fallback test,
  uninstall removing `libexec`); add doctor tests in `tests/self_/test_doctor.py`.

**NOT in scope**: the installers (tasks 2 and 3); `docs/`; `SHA256SUMS`; downloading uv from Python (the runtime
never downloads; only the installers do); `scripts/install/smoke_install.py` (CI smoke test, uses `shutil.which`
on purpose).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/self_/uv.py` | CREATE | Constants, probe, resolver, record, migration |
| `packages/ai-parrot/src/parrot/self_/components.py` | MODIFY | `bundled_uv` delegates; `RUNTIME_DIRS` + `libexec`; `update_runtime` migrates first |
| `packages/ai-parrot/src/parrot/self_/doctor.py` | MODIFY | `_check_uv` via `resolve_uv`; new informational `_check_uv_layout`; import constants |
| `packages/ai-parrot/tests/self_/test_uv.py` | CREATE | Unit tests for the new module |
| `packages/ai-parrot/tests/self_/test_components.py` | MODIFY | Fixture → `libexec`; replace the fallback test; uninstall removes `libexec` |
| `packages/ai-parrot/tests/self_/test_doctor.py` | MODIFY | Tests for `_check_uv` and `_check_uv_layout` |

---

## Codebase Contract (Anti-Hallucination)

Verified against `origin/main` on 2026-11-08.

### Verified Imports
```python
from parrot.launcher import parrot_home  # verified: packages/ai-parrot/src/parrot/launcher.py:26
from parrot.self_ import components     # verified: tests/self_/test_components.py:11
from parrot.self_ import doctor         # verified: tests/self_/test_doctor.py:12
from pydantic import BaseModel          # verified: doctor.py:20 (already a dependency)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/launcher.py:26
def parrot_home(env: Mapping[str, str] | None = None) -> Path:  # $PARROT_HOME or ~/.parrot, NOT resolved, read per call

# packages/ai-parrot/src/parrot/self_/components.py
RUNTIME_DIRS: tuple[str, ...] = ("bin", "venv", "python")          # line 22
def managed_venv() -> Path:                                         # line 54
def bundled_uv() -> Path:                                           # lines 155-171 (body at 164-171 is replaced)
def _run(argv: list[str], log: list[str]) -> None:                  # line 196
def install_component(name: str, *, venv: Path, here: bool = False) -> list[str]:  # line 203; calls bundled_uv() at 229
def update_runtime(version: str | None = None) -> list[str]:        # line 239; python=… at 248, uv=… at 249, log=[] at 250
def uninstall_runtime(*, yes: bool) -> list[str]:                   # line 301; iterates RUNTIME_DIRS

# packages/ai-parrot/src/parrot/self_/doctor.py
PINNED_UV_VERSION: str = "0.11.28"                                  # line 28 (moves to uv.py, re-imported here)
class DoctorCheck(BaseModel):  # line 40 — name, ok, detail="", fix="", informational=False
def _check_uv() -> DoctorCheck:                                     # lines 65-81 (replaced)
def run_doctor(root: Path, *, scope: DoctorScope = "full", install_root: InstallRoot | None = None) -> list[DoctorCheck]:  # line 757
    checks = [_check_uv(), _check_python(), _check_entrypoints(), _check_path(), _check_tools_wiki(),   # line 769
              _check_runtime_lockstep()]

# packages/ai-parrot/tests/self_/test_components.py
def fake_managed_home(tmp_path, monkeypatch) -> Path:  # fixture, lines 14-27; writes bin/uv at line 21
def test_bundled_uv_falls_back_to_path_with_warning(tmp_path, monkeypatch, caplog) -> None:  # lines 72-79 (replaced)
def test_uninstall_keeps_user_data(fake_managed_home) -> None:  # lines 129-132

# packages/ai-parrot/tests/self_/test_doctor.py
def isolated_home(tmp_path, monkeypatch) -> Path:  # fixture, line 16; sets PARROT_HOME=tmp/parrot-home
```

Tests in `test_components.py` patch `components.subprocess.run`, which is the shared `subprocess.run`. Any
`resolve_uv()` reached from them would see the mock and fail to parse a version. The fixture must therefore
monkeypatch `components.bundled_uv` and `components.migrate_legacy_uv`; see the blueprint.

### Does NOT Exist
- ~~`parrot.self_.uv`~~: created by this task.
- ~~`parrot_home()/"libexec"`~~: no code references it yet.
- ~~a uv downloader in Python~~: only the shell / PowerShell installers download uv.
- ~~`uvx` usage in the runtime~~: nothing under `packages/*/src` calls `uvx`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/self_/uv.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/self_/components.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/self_/doctor.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/self_/test_uv.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/self_/test_components.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/self_/test_doctor.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/launcher.py#parrot_home",
    "sym:packages/ai-parrot/src/parrot/self_/components.py#bundled_uv",
    "sym:packages/ai-parrot/src/parrot/self_/components.py#install_component",
    "sym:packages/ai-parrot/src/parrot/self_/components.py#update_runtime",
    "sym:packages/ai-parrot/src/parrot/self_/components.py#uninstall_runtime",
    "sym:packages/ai-parrot/src/parrot/self_/doctor.py#_check_uv",
    "sym:packages/ai-parrot/src/parrot/self_/doctor.py#run_doctor",
    "sym:packages/ai-parrot/tests/self_/test_components.py#test_bundled_uv_falls_back_to_path_with_warning"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The user's uv is never written, moved or deleted. The only files this code may delete or move are
  `parrot_home()/bin/uv` and `bin/uvx` (and `.exe` on Windows); the only files it may create live in
  `parrot_home()/libexec/`.
- Write `uv-path` with `path.absolute()`, **not** `resolve()`. Homebrew's `bin/uv` is a symlink into a versioned
  Cellar directory that disappears on upgrade (brief decision 2).
- `_check_uv` / `_check_uv_layout` stay read-only (doctor contract, `doctor.py:1`). `resolve_uv()` only runs
  `<uv> --version`.
- `bundled_uv()` keeps its name and signature, because both callers (`components.py:229`, `:249`) and the CLI use it.
- Logging is `logger = logging.getLogger(__name__)`; never `print`.

### References in Codebase
- `doctor.py:105-124` (`_check_path`): the resolved-path comparison pattern to reuse when skipping
  `$PARROT_HOME/bin` in the PATH search.
- `components.py:290` (`_installed_version`): the subprocess probe style.

---

## Implementation Blueprint

### Steps (in order)
1. Create `uv.py` from the block below. *Why*: one module owns the range and the layout, and the installers' parity
   tests import it.
2. Rewire `components.py`. *Why*: both callers already use `bundled_uv()`, and `update_runtime` is where
   `parrot self update` migrates (brief decision 6).
3. Rewire `doctor.py`. *Why*: `--runtime-only` must accept a recorded system uv, or the installer rolls back.
4. Write the tests, then run the Validation Commands.

### `packages/ai-parrot/src/parrot/self_/uv.py` (CREATE)
```python
"""Bounded uv resolution for the managed runtime (brief installer-uv-shadowing).

``install-parrot --global`` never puts uv on PATH. It either records the absolute path of a compatible uv the user
already has (``libexec/uv-path``) or downloads the pinned uv into ``libexec/``. ``resolve_uv`` finds it again; an
install from before this fix (uv in ``bin/``, which is on PATH and shadows the user's uv) still resolves, and
``migrate_legacy_uv`` moves it off that layout.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from parrot.launcher import parrot_home  # verified: parrot/launcher.py:26

logger = logging.getLogger(__name__)

#: Downloaded by install-parrot --global when no compatible uv exists.
PINNED_UV_VERSION: str = "0.11.28"
#: Compatible range ``UV_MIN_VERSION <= v < UV_MAX_VERSION`` (uv is 0.x: a minor bump may break).
#: All three are kept equal to scripts/install/install-parrot.{sh,ps1} by tests/docs/test_install_{posix,powershell}.py.
UV_MIN_VERSION: str = "0.11.28"
UV_MAX_VERSION: str = "0.12"
LIBEXEC_DIR: str = "libexec"
UV_PATH_FILE: str = "uv-path"

UvSource = Literal["managed", "recorded", "path", "legacy"]
_VERSION_RE = re.compile(r"\d+(?:\.\d+)*")


class UvResolution(BaseModel):
    """The uv the runtime runs, its version, and where it was found."""

    path: Path
    version: str
    source: UvSource


def _exe(name: str) -> str:
    """``name`` with ``.exe`` on Windows."""
    return f"{name}.exe" if os.name == "nt" else name


def _resolved(path: Path) -> str:
    """Best-effort resolved string form, for PATH-entry comparison only (never stored)."""
    try:
        return str(path.expanduser().resolve())
    except (OSError, RuntimeError):
        return str(path)


def libexec_dir() -> Path:
    """``parrot_home()/libexec``: private, never on PATH."""
    return parrot_home() / LIBEXEC_DIR


def managed_uv() -> Path:
    """The pinned uv downloaded by the installer (``libexec/uv``; ``uv.exe`` on Windows)."""
    return libexec_dir() / _exe("uv")


def uv_path_file() -> Path:
    """One-line text file with the absolute path of the user's compatible uv."""
    return libexec_dir() / UV_PATH_FILE


def legacy_uv_files() -> list[Path]:
    """uv / uvx that pre-fix installers left in ``parrot_home()/bin``, where they shadow the user's uv."""
    bin_dir = parrot_home() / "bin"
    return [p for p in (bin_dir / _exe("uv"), bin_dir / _exe("uvx")) if p.is_file()]


def parse_version(text: str) -> tuple[int, ...] | None:
    """Numeric parts of the first version-like token (``"uv 0.11.28 (abc 2026-01-01)"`` → ``(0, 11, 28)``)."""
    for token in text.split():
        match = _VERSION_RE.match(token)
        if match:
            return tuple(int(part) for part in match.group(0).split("."))
    return None


def _padded(parts: tuple[int, ...], width: int) -> tuple[int, ...]:
    return parts + (0,) * (width - len(parts))


def in_range(version: str | None) -> bool:
    """True iff ``UV_MIN_VERSION <= version < UV_MAX_VERSION``; missing parts compare as 0, garbage is False."""
    parsed = parse_version(version) if version else None
    low, high = parse_version(UV_MIN_VERSION), parse_version(UV_MAX_VERSION)
    if parsed is None or low is None or high is None:
        return False
    width = max(len(parsed), len(low), len(high))
    return _padded(low, width) <= _padded(parsed, width) < _padded(high, width)


def probe_version(path: Path) -> str | None:
    """``<path> --version`` → ``"0.11.28"``; None when it cannot run or prints nothing parsable."""
    try:
        result = subprocess.run([str(path), "--version"], capture_output=True, text=True, check=False, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    parts = parse_version(result.stdout) if result.returncode == 0 else None
    return ".".join(str(p) for p in parts) if parts else None


def find_path_uv() -> Path | None:
    """First ``uv`` on PATH outside ``parrot_home()/bin`` and ``libexec`` (resolved comparison)."""
    own = {_resolved(parrot_home() / "bin"), _resolved(libexec_dir())}
    entries = [e for e in os.environ.get("PATH", "").split(os.pathsep) if e and _resolved(Path(e)) not in own]
    found = shutil.which("uv", path=os.pathsep.join(entries)) if entries else None
    return Path(found).absolute() if found else None


def read_recorded_uv() -> Path | None:
    """The path stored in ``libexec/uv-path`` (first non-empty line), or None."""
    try:
        lines = uv_path_file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    line = next((ln.strip() for ln in lines if ln.strip()), "")
    return Path(line) if line else None


def record_system_uv(path: Path) -> Path:
    """Write ``path`` (absolute, symlinks kept) to ``libexec/uv-path`` write-then-rename; return the file."""
    target = uv_path_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.tmp.{os.getpid()}")
    tmp.write_text(f"{path.absolute()}\n", encoding="utf-8")
    os.replace(tmp, target)
    return target


def _compatible(path: Path | None) -> str | None:
    """Version of ``path`` when it is a file inside the range, else None."""
    if path is None or not path.is_file():
        return None
    version = probe_version(path)
    return version if in_range(version) else None


def resolve_uv() -> UvResolution:
    """The uv the runtime runs: libexec copy → recorded uv-path → PATH → legacy ``bin/uv``, each only when in range.

    Raises:
        FileNotFoundError: no compatible uv; the message names each candidate checked and the fix.
    """
    candidates: list[tuple[UvSource, Path | None]] = [
        ("managed", managed_uv()),
        ("recorded", read_recorded_uv()),
        ("path", find_path_uv()),
        ("legacy", parrot_home() / "bin" / _exe("uv")),
    ]
    tried: list[str] = []
    for source, path in candidates:
        if path is None or not path.is_file():
            continue
        version = probe_version(path)
        if version is not None and in_range(version):
            if source in ("path", "legacy"):
                logger.warning(
                    "using %s uv %s at %s; `parrot self update` or install-parrot --global sets up ~/.parrot/libexec",
                    source, version, path,
                )
            return UvResolution(path=path, version=version, source=source)
        tried.append(f"{path} ({version or 'unknown version'})")
    checked = f"; checked: {', '.join(tried)}" if tried else ""
    raise FileNotFoundError(
        f"no uv in >={UV_MIN_VERSION},<{UV_MAX_VERSION}{checked} — re-run install-parrot --global"
    )


def migrate_legacy_uv() -> list[str]:
    """Move an install off the legacy ``bin/uv`` layout; touch nothing outside ``parrot_home()``.

    A compatible libexec copy or recorded uv makes the legacy files redundant; otherwise a compatible uv on PATH is
    recorded; otherwise the legacy ``bin/uv`` (the old pinned copy) is moved into ``libexec/``. Then ``bin/uv`` and
    ``bin/uvx`` are removed. Without any compatible uv nothing is removed and a warning line explains the fix.

    Returns:
        Human-readable action log (empty when there is nothing to migrate).
    """
    legacy = legacy_uv_files()
    if not legacy:
        return []
    log: list[str] = []
    bin_uv = parrot_home() / "bin" / _exe("uv")
    if _compatible(managed_uv()) or _compatible(read_recorded_uv()):
        pass
    elif (system := find_path_uv()) is not None and _compatible(system):
        record_system_uv(system)
        log.append(f"using your uv at {system}: recorded in {uv_path_file()}")
    elif bin_uv in legacy and _compatible(bin_uv):
        libexec_dir().mkdir(parents=True, exist_ok=True)
        os.replace(bin_uv, managed_uv())
        log.append(f"moved {bin_uv} to {managed_uv()} (off PATH)")
    else:
        log.append(
            f"warning: no uv in >={UV_MIN_VERSION},<{UV_MAX_VERSION} to replace "
            f"{', '.join(str(p) for p in legacy)}; re-run install-parrot --global"
        )
        return log
    for path in legacy:
        if path.exists():
            path.unlink()
            log.append(f"removed legacy {path} (it shadowed the uv on your PATH)")
    return log
```
**Why this shape**: the resolution order and its range gate are brief decision 5. The migration order is decision 6
plus assumption C: remove only after a working replacement is in place. The file is a text record rather than a
symlink (decision 2). Keep all constant names exactly as written, because the parity tests in tasks 2 and 3 import
them.

### `packages/ai-parrot/src/parrot/self_/components.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^from parrot.mcp.toolkit_seed import load_template' components.py)
# AFTER — insert below `from parrot.mcp.toolkit_seed import load_template  # verified: mcp/toolkit_seed.py:63` (line 17)
from parrot.self_.uv import migrate_legacy_uv, resolve_uv  # brief installer-uv-shadowing
```
```python
# REPLACE line 22
RUNTIME_DIRS: tuple[str, ...] = ("bin", "libexec", "venv", "python")
```
```python
# REPLACE the whole body + docstring of bundled_uv (lines 155-171)
def bundled_uv() -> Path:
    """Return the uv the runtime runs (``parrot.self_.uv.resolve_uv``).

    Order: the pinned copy in ``libexec/``, the user's uv recorded in ``libexec/uv-path``, a uv on PATH outside
    ``~/.parrot``, the legacy ``bin/uv``. Each only when its version is in the compatible range.

    Raises:
        FileNotFoundError: no compatible uv — re-run install-parrot --global.
    """
    return resolve_uv().path
```
```python
# REPLACE in update_runtime (lines 248-250):
#     python = _venv_python(managed_venv())
#     uv = str(bundled_uv())
#     log: list[str] = []
python = _venv_python(managed_venv())
log: list[str] = migrate_legacy_uv()  # off the legacy bin/uv layout before resolving uv
uv = str(bundled_uv())
```
Also update the `uninstall_runtime` docstring (line 302) to `(bin/, libexec/, venv/, python/)`. Remove `shutil`
from the imports only if nothing else in `components.py` uses it after this change (verify with grep first).

### `packages/ai-parrot/src/parrot/self_/doctor.py` (MODIFY)
```python
# REPLACE lines 27-28 (the comment + PINNED_UV_VERSION assignment) with:
from parrot.self_.uv import (  # noqa: E402 — brief installer-uv-shadowing; PINNED_UV_VERSION re-exported
    PINNED_UV_VERSION,
    UV_MAX_VERSION,
    UV_MIN_VERSION,
    legacy_uv_files,
    resolve_uv,
)
```
(Better: put this import next to the other `parrot.*` imports at lines 22-23 and drop the `noqa`. Keep
`PINNED_UV_VERSION` importable from `parrot.self_.doctor`, and add it to `__all__` if the module defines one.)
```python
# REPLACE _check_uv (lines 65-81)
def _check_uv() -> DoctorCheck:
    """A uv in ``>=UV_MIN_VERSION,<UV_MAX_VERSION`` resolves (libexec copy, recorded uv, PATH or legacy bin)."""
    try:
        found = resolve_uv()
    except FileNotFoundError as exc:
        return DoctorCheck(name="uv", ok=False, detail=str(exc), fix="re-run install-parrot --global")
    return DoctorCheck(
        name="uv",
        ok=True,
        detail=f"uv {found.version} at {found.path} ({found.source}; compatible >={UV_MIN_VERSION},<{UV_MAX_VERSION})",
    )


def _check_uv_layout() -> DoctorCheck:
    """Informational: uv / uvx left in ~/.parrot/bin by an older installer shadow the user's own uv on PATH."""
    legacy = legacy_uv_files()
    if not legacy:
        return DoctorCheck(name="uv layout", ok=True, informational=True, detail="no uv in ~/.parrot/bin")
    return DoctorCheck(
        name="uv layout",
        ok=False,
        informational=True,
        detail=f"legacy {', '.join(str(p) for p in legacy)} shadow any uv on your PATH",
        fix="parrot self update (or re-run install-parrot --global)",
    )
```
```python
# REPLACE line 769 in run_doctor
    checks = [_check_uv(), _check_uv_layout(), _check_python(), _check_entrypoints(), _check_path(),
              _check_tools_wiki(), _check_runtime_lockstep()]
```
Update the docstring of `_check_uv`, and the module docstring line 3 if it says "pinned uv".

### `packages/ai-parrot/tests/self_/test_components.py` (MODIFY)
```python
# In fake_managed_home (lines 14-27): replace the bin/uv line (21) with a libexec copy, and patch the
# resolver/migration (components.subprocess.run is mocked by the tests, so resolve_uv must not run):
    (home / "bin").mkdir(parents=True)
    (home / "libexec").mkdir()
    (home / "libexec" / f"uv{exe}").write_text("", encoding="utf-8")
    monkeypatch.setattr(components, "bundled_uv", lambda: home / "libexec" / f"uv{exe}")
    monkeypatch.setattr(components, "migrate_legacy_uv", lambda: [])
```
Replace `test_bundled_uv_falls_back_to_path_with_warning` (lines 72-79) with
`test_bundled_uv_delegates_to_resolve_uv`: monkeypatch `components.resolve_uv` to return a `UvResolution` and
assert `bundled_uv()` returns its path. This test does not use `fake_managed_home`. Extend
`test_uninstall_keeps_user_data` with `assert not (fake_managed_home / "libexec").exists()`. Add
`test_update_runtime_migrates_first`: patch `components.migrate_legacy_uv` to return `["moved x"]` and assert the
log starts with that line.

### FILL IN checklist
- [ ] `test_uv.py`: write the Test Specification cases below. POSIX-only cases that execute fake `uv` scripts get
      `@pytest.mark.skipif(os.name == "nt", ...)`.
- [ ] `test_doctor.py`: `_check_uv` ok with a recorded uv (monkeypatch `doctor.resolve_uv`); fail detail and fix
      when it raises; `_check_uv_layout` informational and failing when `bin/uv` exists under `isolated_home`'s
      `PARROT_HOME`, ok when absent; `run_doctor(..., scope="runtime-only")` names include `"uv layout"`.
- [ ] Confirm nothing else in the repo imports `doctor.PINNED_UV_VERSION` in a way that breaks (`grep -rn PINNED_UV_VERSION packages/`).

---

## Acceptance Criteria

- [ ] `resolve_uv()` order: managed → recorded → PATH (skipping `$PARROT_HOME/bin` and `libexec`) → legacy. Each
      candidate counts only in range; otherwise a `FileNotFoundError` that names the candidates and "install-parrot --global".
- [ ] `in_range`: `0.11.27` False, `0.11.28` True, `0.11.99` True, `0.12.0` False, `0.13.7` False, `"garbage"` False, `None` False.
- [ ] `record_system_uv()` stores the absolute, non-resolved path. A symlinked uv is recorded as the link path.
- [ ] `migrate_legacy_uv()` (a) with a compatible system uv: records it and removes `bin/uv` and `bin/uvx`, and the
      system uv's bytes and mtime are unchanged; (b) without one: moves `bin/uv` to `libexec/uv` and removes
      `bin/uvx`; (c) with no legacy files: returns `[]`; (d) with nothing compatible: removes nothing and returns a
      `warning:` line.
- [ ] `update_runtime()` log starts with the migration lines. `uninstall_runtime()` removes `libexec/`.
- [ ] Doctor `--runtime-only` passes with only a recorded system uv; `_check_uv_layout` is informational.
- [ ] `from parrot.self_.doctor import PINNED_UV_VERSION` still works.
- [ ] `ruff check` is clean on every touched file; all Validation Commands pass.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/self_/test_uv.py -q`
- `pytest packages/ai-parrot/tests/self_/test_components.py -q`
- `pytest packages/ai-parrot/tests/self_/test_doctor.py -q`
- `pytest packages/ai-parrot/tests/self_/test_self_cli.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/self_/test_uv.py
"""parrot.self_.uv (brief installer-uv-shadowing). Fake uv binaries are tiny sh scripts printing a version."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from parrot.self_ import uv

posix_only = pytest.mark.skipif(os.name == "nt", reason="fake uv binaries are sh scripts")


def _fake_uv(path: Path, version: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/bin/sh\necho "uv {version} (abc123 2026-01-01)"\n', encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    h = tmp_path / "parrot-home"
    h.mkdir()
    monkeypatch.setenv("PARROT_HOME", str(h))
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    return h


@pytest.mark.parametrize("version, ok", [("0.11.27", False), ("0.11.28", True), ("0.11.99", True),
                                         ("0.12.0", False), ("0.13.7", False), ("garbage", False), (None, False)])
def test_in_range(version, ok) -> None:
    assert uv.in_range(version) is ok


@posix_only
def test_managed_copy_wins(home: Path, tmp_path: Path, monkeypatch) -> None:
    _fake_uv(uv.managed_uv(), "0.11.28")
    system = _fake_uv(tmp_path / "sys" / "uv", "0.11.30")
    monkeypatch.setenv("PATH", str(system.parent))
    assert uv.resolve_uv().source == "managed"


@posix_only
def test_recorded_uv_used_and_out_of_range_skipped(home: Path, tmp_path: Path) -> None:
    system = _fake_uv(tmp_path / "sys" / "uv", "0.11.30")
    uv.record_system_uv(system)
    assert uv.resolve_uv() == uv.UvResolution(path=system, version="0.11.30", source="recorded")
    _fake_uv(system, "0.13.0")  # the user upgraded out of range
    with pytest.raises(FileNotFoundError, match="install-parrot --global"):
        uv.resolve_uv()


@posix_only
def test_path_search_skips_parrot_bin(home: Path, monkeypatch) -> None:
    _fake_uv(home / "bin" / "uv", "0.11.28")
    monkeypatch.setenv("PATH", str(home / "bin"))
    assert uv.find_path_uv() is None
    assert uv.resolve_uv().source == "legacy"


@posix_only
def test_record_keeps_symlink_path(home: Path, tmp_path: Path) -> None:
    real = _fake_uv(tmp_path / "cellar" / "0.11.30" / "uv", "0.11.30")
    link = tmp_path / "brew-bin" / "uv"
    link.parent.mkdir()
    link.symlink_to(real)
    uv.record_system_uv(link)
    assert uv.read_recorded_uv() == link.absolute()


@posix_only
def test_migrate_records_system_uv_and_never_touches_it(home: Path, tmp_path: Path, monkeypatch) -> None:
    _fake_uv(home / "bin" / "uv", "0.11.28")
    _fake_uv(home / "bin" / "uvx", "0.11.28")
    system = _fake_uv(tmp_path / "sys" / "uv", "0.11.30")
    before = (system.read_bytes(), system.stat().st_mtime_ns)
    monkeypatch.setenv("PATH", f"{home / 'bin'}{os.pathsep}{system.parent}")
    log = uv.migrate_legacy_uv()
    assert not (home / "bin" / "uv").exists() and not (home / "bin" / "uvx").exists()
    assert uv.read_recorded_uv() == system and log
    assert (system.read_bytes(), system.stat().st_mtime_ns) == before


@posix_only
def test_migrate_moves_legacy_copy_without_system_uv(home: Path) -> None:
    _fake_uv(home / "bin" / "uv", "0.11.28")
    uv.migrate_legacy_uv()
    assert uv.managed_uv().is_file() and not (home / "bin" / "uv").exists()


def test_migrate_noop_without_legacy(home: Path) -> None:
    assert uv.migrate_legacy_uv() == []


@posix_only
def test_migrate_keeps_files_when_nothing_is_compatible(home: Path) -> None:
    _fake_uv(home / "bin" / "uv", "0.10.0")
    log = uv.migrate_legacy_uv()
    assert (home / "bin" / "uv").exists() and log[0].startswith("warning:")
```

---

## Agent Instructions

1. Work in the brief's worktree (`hotfix-installer-uv-shadowing-installer-uv-shadowing` under the worktree root),
   never on `main`.
2. Read the brief `sdd/briefs/installer-uv-shadowing.brief.md`, in particular Decisions 1, 2, 5 and 6 and
   Assumptions C and D.
3. Verify the Codebase Contract lines before editing. If any have drifted, re-grep and fix the contract first.
4. Touch only the six listed files.
5. Run every Validation Command with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is editable-installed on
   the main checkout). Run `ruff check` on the touched files.
6. Commit code: `fix(self): HOTFIX-installer-uv-shadowing-1 — bounded uv resolver, libexec layout, legacy migration`.
7. Close the task with `parrot sdd task close HOTFIX-installer-uv-shadowing-1 installer-uv-shadowing verified`, fill
   in the Completion Note, and commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
