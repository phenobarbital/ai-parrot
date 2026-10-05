# TASK-4073: Consolidate the three parrot_home() copies onto parrot.launcher.parrot_home

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4071
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 ("single home-path authority") and Module 3 ("Home-path consolidation: the
three existing copies delegate to `parrot.launcher.parrot_home` (import is stdlib-safe)"); codex
S2 (CONFIRM): "Extract PARROT_HOME into dependency-free module; callers delegate".

Today three functions read `PARROT_HOME` independently — with identical semantics (verified
below): `knowledge/wiki/project.py::parrot_home`, `knowledge/bookstore/config.py::_parrot_home`
and the inline read in `cli/modes.py::cli_state_dir`. TASK-4071 created the stdlib-only
`parrot.launcher.parrot_home(env=None)` reproducing exactly that semantics. This task makes
the three call sites delegate to it so the managed home (`$PARROT_HOME/venv`, `bin/`) and the
data home can never drift.

`bookstore/config.py::_parrot_home` is local **on purpose** — its docstring says importing
`bookstore.config` must never drag the wiki module chain in. Delegating to `parrot.launcher`
keeps that guarantee: the launcher imports only the stdlib (plus `parrot`/`parrot.version`,
which `bookstore.config` already loads as a `parrot.*` submodule).

---

## Scope

- Make `parrot.knowledge.wiki.project.parrot_home()` return `parrot.launcher.parrot_home()`.
- Make `parrot.knowledge.bookstore.config._parrot_home()` return `parrot.launcher.parrot_home()`;
  update its docstring to say why the launcher (not the wiki module) is the delegate.
- Make `parrot.cli.modes.cli_state_dir()` build on `parrot.launcher.parrot_home()`, keeping the
  `cli` subdir, `mkdir` and `0o700` chmod exactly.
- Add a test proving all three honour `PARROT_HOME` identically (set / unset / empty / `~`).

**NOT in scope**: renaming or removing any of the three functions (they have callers: 15
`parrot_home()` occurrences in `src/parrot`, def included); changing semantics (no `.resolve()`, no caching);
any other `PARROT_HOME`-like reads elsewhere; launcher code (TASK-4071/4072).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | `parrot_home()` delegates to `parrot.launcher.parrot_home` |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/config.py` | MODIFY | `_parrot_home()` delegates; docstring updated |
| `packages/ai-parrot/src/parrot/cli/modes.py` | MODIFY | `cli_state_dir()` builds on `parrot.launcher.parrot_home` |
| `packages/ai-parrot/tests/launcher/test_parrot_home_consolidation.py` | CREATE | Equivalence tests for the three delegates |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.launcher import parrot_home as _launcher_parrot_home  # created by TASK-4071 (packages/ai-parrot/src/parrot/launcher.py)
from parrot.knowledge.wiki.project import parrot_home             # verified: packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1223
from parrot.knowledge.bookstore.config import _parrot_home        # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/config.py:66
from parrot.cli.modes import cli_state_dir                        # verified: packages/ai-parrot/src/parrot/cli/modes.py:68
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
PARROT_DIR = ".parrot"                                     # line 44 (still used elsewhere: lines 289, 573, 688 — keep it)
def parrot_home() -> Path:                                 # line 1223
    raw = os.environ.get("PARROT_HOME") or f"~/{PARROT_DIR}"   # line 1234
    return Path(raw).expanduser()                              # line 1235

# packages/ai-parrot/src/parrot/knowledge/bookstore/config.py
def _parrot_home() -> Path:                                # line 66 — docstring lines 67-73 ("Kept local ... never drags the wiki module chain in")
    raw = os.environ.get("PARROT_HOME") or "~/.parrot"     # line 74
    return Path(raw).expanduser()                          # line 75
# sole caller: resolve_locations(), line 112: LibraryLocation(scope="global", root=_parrot_home() / "library")
# `os` still needed (line 98: os.environ.get(ENV_LIBRARY_DIR)); `Path` still needed (lines 23, 101)

# packages/ai-parrot/src/parrot/cli/modes.py
def cli_state_dir() -> Path:                               # line 68 — docstring cites "wiki/project.py:1009" (stale line ref)
    raw = os.environ.get("PARROT_HOME") or "~/.parrot"     # line 70
    path = Path(raw).expanduser() / "cli"                  # line 71
    path.mkdir(parents=True, exist_ok=True)                # line 72
    os.chmod(path, 0o700)                                  # line 73
# `os` still needed (chmod/replace at lines 89-123); `Path` still needed (line 117)

# TASK-4071 (dependency): def parrot_home(env: Mapping[str, str] | None = None) -> Path —
#   `(env or os.environ).get("PARROT_HOME") or "~/.parrot"`, `.expanduser()`, no resolve, read per call.
```
**Semantics check (all three copies, verified)**: env read per call; empty string falls back to
the default (`or`); `~` expanded with `expanduser()`; result NOT resolved. They are identical, so
no per-site behaviour needs preserving beyond delegation.

### Does NOT Exist
- ~~any caching of the home path~~ — none exists; must not be introduced (test `test_parrot_home_env_is_read_per_call`).
- ~~a `.resolve()` in any copy~~ — do not add one (would change symlinked-home behaviour).
- ~~`parrot.launcher.parrot_home` before TASK-4071 lands~~ — check the dependency is `done`.
- ~~tests that monkeypatch these functions by attribute~~ — verified none (`grep -rn "setattr(.*parrot_home\|setattr(.*cli_state_dir"` over tests: no hits); tests use `monkeypatch.setenv("PARROT_HOME", ...)`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/project.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/bookstore/config.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/cli/modes.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/launcher/test_parrot_home_consolidation.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#parrot_home",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/config.py#_parrot_home",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/config.py#resolve_locations",
    "sym:packages/ai-parrot/src/parrot/cli/modes.py#cli_state_dir"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Function-body delegation; keep every public/private name, signature and docstring contract.

### Key Constraints
- Import the launcher function under an alias (`_launcher_parrot_home`) at module top — in
  `project.py` the local name `parrot_home` must stay the module's own function (15 `parrot_home()` occurrences across src/parrot, def included).
- `bookstore/config.py` must not gain any import of `parrot.knowledge.wiki.*`.
- Keep `cli_state_dir()`'s side effects (mkdir + chmod 0o700) byte-identical.
- No behaviour change at all: existing tests listed under Validation Commands must pass unchanged.

### References in Codebase
- `packages/ai-parrot/tests/cli/test_modes.py:51` — `test_state_paths_honour_parrot_home_and_perms`
- `tests/knowledge/wiki/test_project_namespaces.py:169` — `test_parrot_home_env_is_read_per_call`
- `packages/ai-parrot/tests/knowledge/bookstore/test_config.py` — PARROT_HOME-driven location tests

---

## Implementation Blueprint

### Steps (in order)
1. Confirm TASK-4071 is `done` and `parrot.launcher.parrot_home` exists — *why*: the only new import.
2. Edit `project.py`, `bookstore/config.py`, `cli/modes.py` — *why*: delegate, no semantic change.
3. Write the equivalence test and run it plus the existing tests — *why*: prove zero drift.

### `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.knowledge.wiki.schema.models import SchemaPlaneConfig' packages/ai-parrot/src/parrot/knowledge/wiki/project.py)
# AFTER — insert below `from parrot.knowledge.wiki.schema.models import SchemaPlaneConfig` (verified: packages/ai-parrot/src/parrot/knowledge/wiki/project.py:30)
from parrot.launcher import parrot_home as _launcher_parrot_home  # FEAT-633: single PARROT_HOME authority (stdlib-only)

# occurrences: 1 (verified: grep -c '    raw = os.environ.get("PARROT_HOME") or f"~/{PARROT_DIR}"' packages/ai-parrot/src/parrot/knowledge/wiki/project.py)
# REPLACE — `    raw = os.environ.get("PARROT_HOME") or f"~/{PARROT_DIR}"` (verified: packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1234)
#   together with the following line `    return Path(raw).expanduser()` (verified: :1235; grep -c → 1)
    return _launcher_parrot_home()
```
**Why**: keeps the public `parrot_home()` (and its docstring, which stays true) while the launcher
becomes the single reader. Append to the docstring: "Delegates to :func:`parrot.launcher.parrot_home` (FEAT-633)."

### `packages/ai-parrot/src/parrot/knowledge/bookstore/config.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^from typing import Literal, Optional' packages/ai-parrot/src/parrot/knowledge/bookstore/config.py)
# AFTER — insert below `from typing import Literal, Optional` (verified: packages/ai-parrot/src/parrot/knowledge/bookstore/config.py:20)
#   (a blank line, then the first-party import group)

from parrot.launcher import parrot_home as _launcher_parrot_home  # stdlib-only: keeps the no-wiki-chain guarantee

# occurrences: 1 (verified: grep -c 'def _parrot_home() -> Path:' packages/ai-parrot/src/parrot/knowledge/bookstore/config.py)
# REPLACE — the body of `def _parrot_home() -> Path:` (verified: packages/ai-parrot/src/parrot/knowledge/bookstore/config.py:66),
#   i.e. docstring lines 67-73 + `    raw = os.environ.get("PARROT_HOME") or "~/.parrot"` (:74, grep -c → 1)
#   + `    return Path(raw).expanduser()` (:75, grep -c → 1)
    """Per-user parrot state dir (``~/.parrot``), ``PARROT_HOME``-overridable.

    Delegates to :func:`parrot.launcher.parrot_home` (FEAT-633), which is
    stdlib-only — so importing ``bookstore.config`` still never drags the
    wiki module chain in, and the contract stays identical to
    :func:`parrot.knowledge.wiki.project.parrot_home`.
    """
    return _launcher_parrot_home()
```
**Why**: the docstring's reason for staying local (no wiki chain) is preserved by delegating to the
stdlib-only launcher rather than to `wiki.project`; say so in the docstring.

### `packages/ai-parrot/src/parrot/cli/modes.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from pydantic import BaseModel, Field  # verified: parrot/cli/repl.py:18' packages/ai-parrot/src/parrot/cli/modes.py)
# AFTER — insert below `from pydantic import BaseModel, Field  # verified: parrot/cli/repl.py:18` (verified: packages/ai-parrot/src/parrot/cli/modes.py:15)

from parrot.launcher import parrot_home  # FEAT-633: single PARROT_HOME authority

# occurrences: 1 (verified: grep -c 'def cli_state_dir() -> Path:' packages/ai-parrot/src/parrot/cli/modes.py)
# REPLACE — docstring + first two body lines of `def cli_state_dir() -> Path:` (verified: packages/ai-parrot/src/parrot/cli/modes.py:68):
#   `    raw = os.environ.get("PARROT_HOME") or "~/.parrot"` (:70, grep -c → 1) and
#   `    path = Path(raw).expanduser() / "cli"` (:71, grep -c → 1); lines 72-74 (mkdir, chmod, return) stay.
    """``parrot.launcher.parrot_home()`` (``$PARROT_HOME`` or ``~/.parrot``) + ``cli``; created ``0o700``."""
    path = parrot_home() / "cli"
```
**Why**: removes the third independent reader; also fixes the stale `wiki/project.py:1009` docstring reference.

### `packages/ai-parrot/tests/launcher/test_parrot_home_consolidation.py` (CREATE)
```python
"""All three PARROT_HOME readers agree with parrot.launcher.parrot_home (FEAT-633, TASK-4073)."""
from __future__ import annotations

from pathlib import Path

import pytest

from parrot.cli.modes import cli_state_dir
from parrot.knowledge.bookstore.config import _parrot_home
from parrot.knowledge.wiki.project import parrot_home
from parrot.launcher import parrot_home as launcher_parrot_home  # created by TASK-4071


@pytest.mark.parametrize("value", [None, "", "~/custom-home", "ABS"])
def test_three_readers_identical(value, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    if value is None:
        monkeypatch.delenv("PARROT_HOME", raising=False)
    else:
        monkeypatch.setenv("PARROT_HOME", str(tmp_path / "abs-home") if value == "ABS" else value)
    expected = launcher_parrot_home()
    assert parrot_home() == expected
    assert _parrot_home() == expected
    assert cli_state_dir() == expected / "cli"


def test_default_and_tilde_semantics(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PARROT_HOME", "")
    assert parrot_home() == tmp_path / ".parrot"             # empty ⇒ default (``or`` semantics)
    monkeypatch.setenv("PARROT_HOME", "~/x")
    assert _parrot_home() == tmp_path / "x"                  # ``~`` expanded
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "link"))
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
    assert parrot_home() == tmp_path / "link"                # NOT resolved


def test_bookstore_config_does_not_import_wiki_chain():
    # FILL IN: subprocess `python -c "import sys, parrot.knowledge.bookstore.config; print(any(m.startswith('parrot.knowledge.wiki') for m in sys.modules))"`
    #   and assert "False" — bounded by bookstore/config.py docstring guarantee (lines 67-73)
    raise NotImplementedError
```

### FILL IN checklist
- [ ] `test_parrot_home_consolidation.py::test_bookstore_config_does_not_import_wiki_chain` — subprocess check; bounded by the bookstore docstring guarantee (if `parrot.knowledge.bookstore/__init__.py` already imports the wiki chain today, record that in the Completion Note and assert "no NEW wiki import" against a baseline instead)

---

## Acceptance Criteria

- [ ] `parrot.knowledge.wiki.project.parrot_home`, `parrot.knowledge.bookstore.config._parrot_home` and `parrot.cli.modes.cli_state_dir` contain no direct `PARROT_HOME` read; each delegates to `parrot.launcher.parrot_home` (`grep -n 'environ.get("PARROT_HOME")'` on the three files returns nothing).
- [ ] All three return identical results for PARROT_HOME unset / empty / `~`-relative / absolute; no `.resolve()` introduced; env read per call.
- [ ] `bookstore.config` still imports no `parrot.knowledge.wiki.*` module.
- [ ] Existing tests pass unchanged (Validation Commands).
- [ ] `ruff check` on the three modified files and the new test passes.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/launcher/test_parrot_home_consolidation.py -q`
- `pytest packages/ai-parrot/tests/cli/test_modes.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_config.py -q`
- `pytest tests/knowledge/wiki/test_project_namespaces.py::test_parrot_home_env_is_read_per_call -q`

---

## Test Specification

The `test_parrot_home_consolidation.py` blueprint block above is the scaffold: a parametrized
equivalence test over the four PARROT_HOME states, explicit default/tilde/no-resolve checks, and a
subprocess import-chain guard for `bookstore.config`.

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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4073 parrot-installer verified`
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
