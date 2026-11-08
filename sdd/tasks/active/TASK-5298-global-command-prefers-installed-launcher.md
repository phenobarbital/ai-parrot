# TASK-5298: Google global toolkit command prefers the installed managed launcher

**Feature**: FEAT-838 — Google installer prefers the installed managed launcher
**Spec**: `sdd/specs/google-installer-fixes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:e92e5f160cdd`

---

## Context

Ledger issue `issue:e92e5f160cdd`: with a repository venv active, `.venv/bin` shadows `~/.parrot/bin`
on `PATH`, so `_global_parrot_command()` misses the installed managed launcher and inherits whichever
repository's `parrot` binary already sits in `~/.gemini/config/mcp_config.json`. Implements spec §2 and
all of §5 (AC-1..AC-4).

---

## Scope

- Add rule 1b to `_global_parrot_command`: when `parrot_home()/"bin"/"parrot"` (`parrot.exe` on Windows)
  AND `script_path(parrot_home()/"venv", "parrot")` both exist, return `"parrot"`. Keep rule 1 (PATH).
- When rule 2 reuses an absolute command not inside `root` (resolved), `logger.warning(...)` naming the
  entry and the command.
- Update the docstring to the new order.
- Write `packages/ai-parrot/tests/knowledge/wiki/test_google_global_command.py`.

**NOT in scope**: `parrot/sdd/installer.py::guard_hook_command`, `launcher.managed_launcher_on_path`,
`resolve_portable_mode`, entry `args`, the repo-local plugin config.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py` | MODIFY | rule 1b + cross-repo warning in `_global_parrot_command` |
| `packages/ai-parrot/tests/knowledge/wiki/test_google_global_command.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.launcher import parrot_home, script_path  # verified: launcher.py:26, launcher.py:198
from parrot.knowledge.wiki.google import assets         # verified: installer.py:12
from parrot.knowledge.wiki.google.installer import _global_parrot_command  # verified: installer.py:186
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py
# module imports json, logging, shutil, sys, Path (lines 5-9) — `os` is NOT imported; use sys.platform
logger = logging.getLogger(__name__)                              # line 18
def _is_parrot_toolkit_shape(entry: Any, name: str) -> bool:      # line 172
def _global_parrot_command(root: Path, existing: dict[str, Any]) -> str:  # line 186; local import of parrot_home at line 193
# called from reconcile_toolkit_entries at line 297: command = "parrot" if portable else _global_parrot_command(root, servers)

# packages/ai-parrot/src/parrot/launcher.py
def parrot_home(env: Mapping[str, str] | None = None) -> Path:    # line 26 — reads $PARROT_HOME, not resolved
def script_path(venv: Path, name: str, *, os_name: str | None = None) -> Path:  # line 198 — venv/bin/<name> or venv/Scripts/<name>.exe

# packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py
def resolve_binary(root: Path, name: str) -> str:                 # line 70 — project venv, then PATH, then bare name

# packages/ai-parrot/src/parrot/self_/doctor.py:129-131 (precedent for the shim location)
home_bin = parrot_home() / "bin"; (home_bin / (f"{n}.exe" if os.name == "nt" else n)).exists() and script_path(managed_venv(), n).exists()
```

### Does NOT Exist
- ~~`parrot.launcher.managed_launcher_installed`~~ — no such helper; implement the check inline.
- ~~`parrot.launcher.launcher_bin_dir`~~ / ~~`parrot_bin()`~~ — no such helper; use `parrot_home() / "bin"`.
- ~~`assets.global_parrot_command`~~ — the function lives only in `installer.py`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_google_global_command.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#_global_parrot_command",
    "sym:packages/ai-parrot/src/parrot/launcher.py#parrot_home",
    "sym:packages/ai-parrot/src/parrot/launcher.py#script_path"
  ]
}
```

---

## Implementation Notes

- Wrap the rule 1b probes in `try/except OSError` → treat as not installed (spec §2).
- "Inside root": `Path(command).resolve()` equals `root.resolve()` or has it in `.parents`. Bare `"parrot"`
  is never warned about.
- Tests: mirror `isolated_env` from `tests/knowledge/wiki/test_google_portable.py:170-182` (HOME,
  PARROT_HOME, PATH under `tmp_path`); use `caplog` for the warning.

---

## Implementation Blueprint

### Steps (in order)
1. Import `script_path` next to `parrot_home` in the function's local import — *why*: keeps the existing local-import pattern (avoids import cycles at module load).
2. Insert rule 1b after the PATH loop — *why*: AC-1, PATH order must not matter once the launcher is installed.
3. Add the warning in rule 2 before `return command` — *why*: AC-3.
4. Write the tests, run them and the contract tests.

### `packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    from parrot.launcher import parrot_home' installer.py)
# REPLACE `    from parrot.launcher import parrot_home` (verified: installer.py:193) with:
    from parrot.launcher import parrot_home, script_path

# occurrences: 1 (verified: grep -c 'found = shutil.which("parrot")' installer.py)
# AFTER the `if found:` block that ends with `return "parrot"` (installer.py:195-201), insert:
    try:
        home = parrot_home()
        shim = home / "bin" / ("parrot.exe" if sys.platform == "win32" else "parrot")
        if shim.is_file() and script_path(home / "venv", "parrot").is_file():
            return "parrot"
    except OSError:
        pass

# In the rule-2 loop, before `return command` (installer.py:206):
    # FILL IN: if command != "parrot" and Path(command).resolve() is not root.resolve() / under it,
    #          logger.warning naming `name`, `command`, and the fix (`parrot self install` or `--portable`) — AC-3
```
**Why**: rule 1b mirrors `doctor._check_entrypoints` so "installed" means the same thing everywhere; rule 1 stays because existing tests only put the shim on PATH.

### `packages/ai-parrot/tests/knowledge/wiki/test_google_global_command.py` (CREATE)
```python
"""FEAT-838 — `_global_parrot_command` prefers the installed managed launcher (issue:e92e5f160cdd)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from parrot.knowledge.wiki.google import assets
from parrot.knowledge.wiki.google.installer import _global_parrot_command


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """HOME / PARROT_HOME / PATH under tmp_path; PATH holds only a repo-venv ``parrot``."""
    # FILL IN: create home, parrot_home, a repo root with .venv/bin/parrot (executable) and put that dir on PATH


def _install_launcher(parrot_home: Path, *, venv: bool = True) -> None:
    # FILL IN: write parrot_home/bin/parrot and (when venv) parrot_home/venv/bin/parrot, both executable


def _entry(command: str) -> dict:
    return {"command": command, "args": ["mcp-local", "memory"]}

# FILL IN: the five tests from spec §4 (names verbatim)
```

### FILL IN checklist
- [ ] warning condition + message — AC-3
- [ ] `env` fixture and `_install_launcher`
- [ ] five tests from spec §4 — AC-1, AC-2, AC-3

---

## Acceptance Criteria

- [ ] AC-1 installed launcher (shim + managed venv) → `"parrot"` even when a repo `parrot` comes first on PATH and an existing entry points at another repo
- [ ] AC-2 shim not on PATH and no managed venv script → not installed
- [ ] AC-3 rule 2 reusing an absolute command outside `root` logs a WARNING naming it
- [ ] AC-4 tests below pass; `ruff check` clean on both files

---

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_google_global_command.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py -q`

---

## Test Specification

See spec §4 table; the scaffold is in the blueprint above.

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug google-installer-fixes --feature-id FEAT-838`).
2. Verify the Codebase Contract, implement from the blueprint, run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src`.
3. Commit only the two files; close with `parrot sdd task close TASK-5298 google-installer-fixes verified`.

---

## Completion Note

*(Agent fills this in when done)*
