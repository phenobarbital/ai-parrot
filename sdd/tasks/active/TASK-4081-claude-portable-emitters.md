# TASK-4081: Claude host: Windows script paths + portable entry emitters (assets + bookstore)

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4071
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (host portability), parts (a), (b) and (d), for the **Claude Code** host — emitter
layer only. Today every Claude entry emitter bakes absolute, POSIX-only paths:
`resolve_wikitoolkit_bin` / `resolve_parrot_bin` probe `<root>/.venv/bin/<name>` (no Windows
`Scripts\<name>.exe` branch), toolkit entries pin an absolute `--config` and `cwd` (FEAT-556), and
the bookstore entry pins `sys.executable -m parrot.knowledge.bookstore.cli mcp` with an absolute `cwd`.

This task makes the emitters (1) Windows-correct via `parrot.launcher.script_path` (created by
TASK-4071) and (2) able to emit a **portable** form behind a keyword-only `portable: bool = False`.
Default emission must stay byte-identical to today (spec §5: "Default host emission (no `--portable`)
is unchanged except the Windows fix"). The installer/CLI threading, the reconcile rule and the
`--portable` flag are TASK-4082 — this task changes **no installer logic**.

Portable form per field (shared brief, cross-cutting decision):
- `command` = bare console-script name (`wikitoolkit`, `parrot`, `bookstore`);
- no absolute path in `command`, `args` or `cwd`; toolkit `--config` becomes the relative
  `.parrot/mcp-toolkits.yaml`; `cwd` is omitted;
- `PARROT_PROJECT` in `env` only if spike S3 (TASK-4069) shows the host expands variables —
  otherwise omitted (FILL IN below).

---

## Scope

- Replace the `root / ".venv" / "bin" / <name>` probes in `resolve_wikitoolkit_bin` and
  `resolve_parrot_bin` with `script_path(root / ".venv", <name>)`.
- Add keyword-only `portable: bool = False` to `hook_command`, `mcp_json_entry`,
  `toolkit_mcp_json_entry` and `permission_rules` in `claude_code/assets.py`.
- Add the module constant `PORTABLE_TOOLKIT_CONFIG = ".parrot/mcp-toolkits.yaml"` (TASK-4082's
  managed-entry detection matches it).
- In `claude_code/bookstore.py`: add `portable` to `mcp_json_entry` (portable form
  `{"command": "bookstore", "args": ["mcp"], "env": {}}`), teach `_is_managed_entry` to recognise
  the portable shape, and thread `portable` through `install_bookstore` (keyword-only, default False).
- Write `packages/ai-parrot/tests/knowledge/wiki/test_claude_portable_emitters.py`.

**NOT in scope**:
- `claude_code/installer.py` and `claude_code/cli.py` (`--portable` flag, reconcile rule,
  stickiness, `PurePosixPath` fixes) — TASK-4082.
- `git_hook_block` / `git_hook_new_file`: they write into `.git/hooks/`, which is never committed,
  so they stay baked in both modes (they still get the Windows fix through `resolve_wikitoolkit_bin`).
- `PERMISSION_RULES` (assets.py:53-68) — keep exactly as is.
- Codex and Google hosts — TASK-4083 / TASK-4084.
- Making `parrot mcp-local` honour `PARROT_PROJECT` (it resolves its root from `Path.cwd()`,
  `mcp/local_cli.py:183`) — not owned by this task.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` | MODIFY | Windows branch via `script_path`; `portable=` on hook/MCP/toolkit/permission emitters; `PORTABLE_TOOLKIT_CONFIG` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/bookstore.py` | MODIFY | Portable bookstore entry (`bookstore mcp`), portable-aware managed detection, `install_bookstore(portable=)` |
| `packages/ai-parrot/tests/knowledge/wiki/test_claude_portable_emitters.py` | CREATE | Unit tests for both emitter modes + Windows branch |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (branch `dev` @ `6c4ca5482`, 2026-10-05).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.launcher import script_path   # CREATED BY TASK-4071 — script_path(venv: Path, name: str) -> Path
                                          # (spec §3 M1: venv/'bin'/name on POSIX; venv/'Scripts'/f'{name}.exe' on Windows)
from parrot.knowledge.wiki.claude_code import assets                    # packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py
from parrot.knowledge.wiki.claude_code import bookstore                 # packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/bookstore.py
from parrot.knowledge.bookstore.config import resolve_locations         # used by bookstore.py:16 (unchanged)
from parrot.mcp.toolkit_config import ToolkitSection                    # packages/ai-parrot/src/parrot/mcp/toolkit_config.py:20 (env field line 57)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py
PERMISSION_RULES: tuple[str, ...] = (...)                                   # line 53-68 — KEEP UNCHANGED
MCP_JSON_ENTRY: dict = {"command": "wikitoolkit", "args": ["mcp"], "env": {}}  # line 76-80 (already the portable wikitoolkit shape)
def resolve_wikitoolkit_bin(root: Path) -> str:                             # line 88; probe at line 100: root / ".venv" / "bin" / "wikitoolkit"
def hook_command(root: Path) -> str:                                        # line 109 -> f"{resolve_wikitoolkit_bin(root)} claude-hook"
def mcp_json_entry(root: Path) -> dict:                                     # line 114 -> {"command": abs, "args": ["mcp"], "env": {}}
def resolve_parrot_bin(root: Path) -> str:                                  # line 123; probe at line 136: root / ".venv" / "bin" / "parrot"
def toolkit_mcp_json_entry(root: Path, name: str, section: ToolkitSection) -> dict:  # line 145-168
#   returns {"command": resolve_parrot_bin(root),
#            "args": ["mcp-local", name, "--config", str(root / ".parrot" / "mcp-toolkits.yaml")],
#            "cwd": str(root), "env": dict(section.env)}       # FEAT-556 pin, comment at lines 162-164
def git_hook_block(root: Path) -> str:                                      # line 171 (unchanged)
def permission_rules(root: Path) -> tuple[str, ...]:                        # line 204-214 (bare -> PERMISSION_RULES; else + f"Bash({resolved}:*)")

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/bookstore.py
_MANAGED_ARGS = ["-m", "parrot.knowledge.bookstore.cli", "mcp"]            # line 30
def mcp_json_entry(root: Path) -> dict:                                     # line 33; "command": sys.executable line 36; "cwd": str(root.resolve()) line 38
def _is_managed_entry(entry: Any) -> bool:                                  # line 43; body line 45: args == _MANAGED_ARGS
def install_bookstore(root: Path) -> list[str]:                             # line 72; entry = mcp_json_entry(root) line 91; existing == entry line 93
def uninstall_bookstore(root: Path) -> list[str]:                           # line 117 (uses _is_managed_entry — portable entries must be removable)

# packages/ai-parrot/pyproject.toml:199-206 — console scripts `parrot`, `wikitoolkit`, `bookstore` exist;
# packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py:587 — `@bookstore.command("mcp")` exists, so `bookstore mcp` is valid.
```

### Does NOT Exist
- ~~`parrot/launcher.py` on `dev` today~~ — created by TASK-4071; do not start before it is `done`.
- ~~Any Windows venv handling (`Scripts\`, `.exe`) in `claude_code/`~~ — none exists; this task adds it via `script_path` only (never a local `os.name` branch).
- ~~a `portable` parameter on any emitter~~ — none exists today.
- ~~`PORTABLE_TOOLKIT_CONFIG`~~ — new constant in this task.
- ~~`parrot mcp-local` honouring `PARROT_PROJECT`~~ — it uses `Path.cwd()` (`mcp/local_cli.py:183`); a relative `--config` resolves against the process cwd.
- ~~a `bookstore` console-script variant taking `--project`~~ — not a thing; portable bookstore entry is exactly `bookstore mcp`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/bookstore.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_claude_portable_emitters.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py#resolve_wikitoolkit_bin",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py#hook_command",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py#mcp_json_entry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py#resolve_parrot_bin",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py#toolkit_mcp_json_entry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py#git_hook_block",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py#permission_rules",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py#PERMISSION_RULES",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py#MCP_JSON_ENTRY",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/bookstore.py#mcp_json_entry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/bookstore.py#_is_managed_entry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/bookstore.py#install_bookstore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/bookstore.py#uninstall_bookstore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/bookstore.py#_MANAGED_ARGS",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#ToolkitSection"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# The existing "MCP_JSON_ENTRY" constant (assets.py:76) IS the portable wikitoolkit shape.
# Portable emitters return fresh copies (never the shared dict/list objects), e.g.:
{"command": MCP_JSON_ENTRY["command"], "args": list(MCP_JSON_ENTRY["args"]), "env": {}}
```

### Key Constraints
- **Default output is byte-identical to today** on POSIX (same keys, same key order, same values).
  The only default-mode change is that `.venv\Scripts\<name>.exe` is found on Windows.
- `portable` is **keyword-only** on every emitter (`*, portable: bool = False`) so no positional
  caller changes meaning.
- Portable emission must be **root-independent**: two different roots produce equal dicts (this is
  what makes TASK-4084's user-global Gemini config and a committed `.mcp.json` work).
- `parrot.launcher` is stdlib-only (TASK-4071), so a module-level `from parrot.launcher import
  script_path` is cheap and adds no import-order risk.
- No `print()`; these are pure functions — no logging needed.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py:693-743` — the consumer
  (`_install_mcp_json`) that TASK-4082 threads `portable` into.
- `packages/ai-parrot/src/parrot/mcp/local_cli.py:164-209` — how `parrot mcp-local` resolves its
  root (`Path.cwd()`) and `--config` (click `Path`, relative to cwd).

---

## Implementation Blueprint

### Steps (in order)
1. Import `script_path` and rewrite both venv probes — *why*: spec §3 M5(a), every
   `root/.venv/bin/<name>` resolution goes through `parrot.launcher.script_path`.
2. Add `PORTABLE_TOOLKIT_CONFIG` next to `MCP_JSON_ENTRY` — *why*: one shared literal for the
   emitter (here) and the managed-entry detector (TASK-4082).
3. Add `*, portable: bool = False` to `hook_command`, `mcp_json_entry`, `toolkit_mcp_json_entry`,
   `permission_rules` — *why*: spec §3 M5(b), keyword threaded to the emitters.
4. Bookstore: portable `mcp_json_entry`, portable-aware `_is_managed_entry`, `install_bookstore(…,
   *, portable=False)` — *why*: spec §3 M5(b)/(d), bookstore `sys.executable` pin replaced in
   portable mode; a portable entry must still be recognised as ours so re-install/uninstall manage it.
5. Write the tests — *why*: spec §4 `test_portable_entries_no_abs_paths`, `test_default_emission_unchanged`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from typing import TYPE_CHECKING' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py)
# AFTER — insert below `from typing import TYPE_CHECKING` (verified: claude_code/assets.py:13)

from parrot.launcher import script_path  # created by TASK-4071 (stdlib-only module)

# occurrences: 1 (verified: grep -c 'MCP_JSON_ENTRY: dict = {' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py)
# AFTER — insert below the closing `}` of `MCP_JSON_ENTRY: dict = {` (verified: claude_code/assets.py:76-80)

#: Relative toolkit config used by portable toolkit entries (FEAT-633). Resolved by
#: ``parrot mcp-local`` against the process cwd (mcp/local_cli.py:183).
PORTABLE_TOOLKIT_CONFIG = ".parrot/mcp-toolkits.yaml"

# occurrences: 1 (verified: grep -c '    venv_bin = root / ".venv" / "bin" / "wikitoolkit"' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py)
# REPLACE — `    venv_bin = root / ".venv" / "bin" / "wikitoolkit"` (verified: claude_code/assets.py:100)
    venv_bin = script_path(root / ".venv", "wikitoolkit")
# (also update the docstring item 1 to "<root>/.venv/bin/wikitoolkit (``Scripts\\wikitoolkit.exe`` on Windows)")

# occurrences: 1 (verified: grep -c '    venv_bin = root / ".venv" / "bin" / "parrot"' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py)
# REPLACE — `    venv_bin = root / ".venv" / "bin" / "parrot"` (verified: claude_code/assets.py:136)
    venv_bin = script_path(root / ".venv", "parrot")

# occurrences: 1 (verified: grep -c 'def hook_command(root: Path) -> str:' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py)
# REPLACE — whole function `def hook_command(root: Path) -> str:` (verified: claude_code/assets.py:109-111)
def hook_command(root: Path, *, portable: bool = False) -> str:
    """Build the ``PreToolUse`` hook command.

    Args:
        root: Project root used to resolve the ``wikitoolkit`` binary.
        portable: Emit the bare ``wikitoolkit claude-hook`` (committable; relies on the
            FEAT-633 launcher being on PATH) instead of the resolved absolute path.
    """
    if portable:
        return HOOK_COMMAND
    return f"{resolve_wikitoolkit_bin(root)} claude-hook"

# occurrences: 1 (verified: grep -c 'def mcp_json_entry(root: Path) -> dict:' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py)
# REPLACE — whole function `def mcp_json_entry(root: Path) -> dict:` (verified: claude_code/assets.py:114-120)
def mcp_json_entry(root: Path, *, portable: bool = False) -> dict:
    """Build the ``.mcp.json`` wikitoolkit entry (absolute path, or portable bare command)."""
    if portable:
        entry = {"command": MCP_JSON_ENTRY["command"], "args": list(MCP_JSON_ENTRY["args"]), "env": {}}
        # FILL IN: add {"PARROT_PROJECT": "<host variable reference>"} to entry["env"] ONLY if spike
        # S3 (TASK-4069, sdd/state/FEAT-633/spikes/) shows Claude Code expands it; never an absolute
        # path — bounded by spec §5 "no machine-specific absolute path in any field … env included".
        return entry
    return {
        "command": resolve_wikitoolkit_bin(root),
        "args": ["mcp"],
        "env": {},
    }
```
**Why this shape**: the default branch is the verbatim old body, so default output cannot drift.

```python
# occurrences: 1 (verified: grep -c 'def toolkit_mcp_json_entry(root: Path, name: str, section: ToolkitSection) -> dict:' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py)
# REPLACE — signature line + return statement of `toolkit_mcp_json_entry` (verified: claude_code/assets.py:145, 160-168); keep the docstring, add `portable` to Args/Returns
def toolkit_mcp_json_entry(root: Path, name: str, section: ToolkitSection, *, portable: bool = False) -> dict:
    # ... existing docstring, plus:
    #     portable: Emit ``{"command": "parrot", "args": ["mcp-local", name, "--config",
    #         PORTABLE_TOOLKIT_CONFIG], "env": dict(section.env)}`` — no ``cwd``, no absolute path.
    if portable:
        entry: dict = {
            "command": "parrot",
            "args": ["mcp-local", name, "--config", PORTABLE_TOOLKIT_CONFIG],
            "env": dict(section.env),
        }
        # FILL IN: PARROT_PROJECT env pin, same rule as mcp_json_entry — bounded by spike S3
        # evidence; omit when Claude Code does not expand variables (cwd = project root is then relied on).
        return entry
    return {
        "command": resolve_parrot_bin(root),
        # Pinned (FEAT-556): ... (keep the existing comment verbatim)
        "args": ["mcp-local", name, "--config", str(root / ".parrot" / "mcp-toolkits.yaml")],
        "cwd": str(root),
        "env": dict(section.env),
    }

# occurrences: 1 (verified: grep -c 'def permission_rules(root: Path) -> tuple[str, ...]:' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py)
# REPLACE — whole function `def permission_rules(root: Path) -> tuple[str, ...]:` (verified: claude_code/assets.py:204-214)
def permission_rules(root: Path, *, portable: bool = False) -> tuple[str, ...]:
    """Return permission rules, plus the absolute-path variant in baked mode.

    In portable mode the command is the bare ``wikitoolkit``, which the static
    :data:`PERMISSION_RULES` already cover — no machine-specific rule is added.
    """
    if portable:
        return PERMISSION_RULES
    resolved = resolve_wikitoolkit_bin(root)
    if resolved == "wikitoolkit":
        return PERMISSION_RULES
    return PERMISSION_RULES + (f"Bash({resolved}:*)",)
```
**Why**: portable entries must carry no absolute path in any field (spec §5); `cwd` is dropped and
`--config` made relative per the per-field contract (spec §3 M5(d)).

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/bookstore.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '_MANAGED_ARGS = \["-m", "parrot.knowledge.bookstore.cli", "mcp"\]' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/bookstore.py)
# AFTER — insert below `_MANAGED_ARGS = ["-m", "parrot.knowledge.bookstore.cli", "mcp"]` (verified: claude_code/bookstore.py:30)

#: Portable (FEAT-633) managed shape: the ``bookstore`` console script, no ``cwd``.
_PORTABLE_COMMAND = "bookstore"
_PORTABLE_ARGS = ["mcp"]

# occurrences: 1 (verified: grep -c 'def mcp_json_entry(root: Path) -> dict:' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/bookstore.py)
# REPLACE — whole function (verified: claude_code/bookstore.py:33-40; anchor `        "command": sys.executable,` at :36)
def mcp_json_entry(root: Path, *, portable: bool = False) -> dict:
    """Build the managed ``.mcp.json`` entry for the bookstore MCP server.

    Args:
        root: Project root (baked mode pins it as ``cwd``).
        portable: Emit ``{"command": "bookstore", "args": ["mcp"], "env": {}}`` — no
            ``sys.executable`` pin and no absolute ``cwd`` (the host's cwd scopes the library).
    """
    if portable:
        return {"command": _PORTABLE_COMMAND, "args": list(_PORTABLE_ARGS), "env": {}}
    return {
        "command": sys.executable,
        "args": list(_MANAGED_ARGS),
        "cwd": str(root.resolve()),
        "env": {},
    }

# occurrences: 1 (verified: grep -c '    return isinstance(entry, dict) and entry.get("args") == _MANAGED_ARGS' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/bookstore.py)
# REPLACE — body line of `_is_managed_entry` (verified: claude_code/bookstore.py:45)
    if not isinstance(entry, dict):
        return False
    if entry.get("args") == _MANAGED_ARGS:
        return True
    return entry.get("command") == _PORTABLE_COMMAND and entry.get("args") == _PORTABLE_ARGS

# occurrences: 1 (verified: grep -c 'def install_bookstore(root: Path) -> list\[str\]:' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/bookstore.py)
# REPLACE — signature `def install_bookstore(root: Path) -> list[str]:` (verified: claude_code/bookstore.py:72)
def install_bookstore(root: Path, *, portable: bool = False) -> list[str]:

# occurrences: 1 (verified: grep -c '    entry = mcp_json_entry(root)' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/bookstore.py)
# REPLACE — `    entry = mcp_json_entry(root)` (verified: claude_code/bookstore.py:91)
    entry = mcp_json_entry(root, portable=portable)
```
**Why**: the existing `existing == entry` / `_is_managed_entry` branches (lines 93-100) then give
"requested mode wins" for a managed entry and "user entry preserved" for a foreign one, with no new
branch. `uninstall_bookstore` removes portable entries too because it reuses `_is_managed_entry`.

### `packages/ai-parrot/tests/knowledge/wiki/test_claude_portable_emitters.py` (CREATE)
```python
"""FEAT-633 TASK-4081 — Claude Code emitters: Windows script paths + portable form."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Iterator

import pytest
from parrot.knowledge.wiki.claude_code import assets, bookstore
from parrot.mcp.toolkit_config import ToolkitSection


def _strings(value: Any) -> Iterator[str]:
    """Yield every string nested in an emitted entry (keys excluded)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _assert_no_abs_paths(entry: Any, root: Path) -> None:
    for text in _strings(entry):
        assert not os.path.isabs(text), text
        assert str(root) not in text and sys.executable not in text, text


def _section() -> ToolkitSection:
    # FILL IN: build a minimal enabled ToolkitSection (verify required fields at
    # mcp/toolkit_config.py:20-57) — bounded by: no env, so portable output has no user paths.
    raise NotImplementedError


def test_portable_entries_no_abs_paths(tmp_path: Path) -> None:
    """Spec §4: portable wikitoolkit/toolkit/bookstore entries + hook carry no absolute path."""
    entries = [
        assets.mcp_json_entry(tmp_path, portable=True),
        assets.toolkit_mcp_json_entry(tmp_path, "memory", _section(), portable=True),
        bookstore.mcp_json_entry(tmp_path, portable=True),
        assets.hook_command(tmp_path, portable=True),
    ]
    for entry in entries:
        _assert_no_abs_paths(entry, tmp_path)
    assert bookstore.mcp_json_entry(tmp_path, portable=True)["command"] == "bookstore"
    assert "cwd" not in assets.toolkit_mcp_json_entry(tmp_path, "memory", _section(), portable=True)


def test_portable_entries_root_independent(tmp_path: Path) -> None:
    """Two roots produce identical portable entries (committable)."""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert assets.mcp_json_entry(a, portable=True) == assets.mcp_json_entry(b, portable=True)
    assert bookstore.mcp_json_entry(a, portable=True) == bookstore.mcp_json_entry(b, portable=True)


def test_default_emission_unchanged(tmp_path: Path) -> None:
    """Spec §4: without portable, emitters return exactly today's shapes."""
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "wikitoolkit").write_text("")
    (venv_bin / "parrot").write_text("")
    assert assets.mcp_json_entry(tmp_path) == {"command": str(venv_bin / "wikitoolkit"), "args": ["mcp"], "env": {}}
    assert bookstore.mcp_json_entry(tmp_path) == {
        "command": sys.executable,
        "args": ["-m", "parrot.knowledge.bookstore.cli", "mcp"],
        "cwd": str(tmp_path.resolve()),
        "env": {},
    }
    # FILL IN: assert toolkit_mcp_json_entry default == the FEAT-556 pinned dict (assets.py:160-168)
    # and permission_rules(tmp_path) ends with f"Bash({venv_bin / 'wikitoolkit'}:*)".


def test_windows_scripts_branch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A Windows venv (Scripts\\<name>.exe) is resolved through launcher.script_path."""
    monkeypatch.setattr(assets, "script_path", lambda venv, name: venv / "Scripts" / f"{name}.exe")
    exe = tmp_path / ".venv" / "Scripts" / "wikitoolkit.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert assets.resolve_wikitoolkit_bin(tmp_path) == str(exe)


def test_bookstore_managed_detection_accepts_portable() -> None:
    assert bookstore._is_managed_entry({"command": "bookstore", "args": ["mcp"], "env": {}})
    assert bookstore._is_managed_entry({"command": "/x/python", "args": ["-m", "parrot.knowledge.bookstore.cli", "mcp"]})
    assert not bookstore._is_managed_entry({"command": "my-bookstore", "args": ["mcp"]})
```

### FILL IN checklist
- [ ] `assets.py::mcp_json_entry` / `toolkit_mcp_json_entry` — `PARROT_PROJECT` env pin or omit; bounded by spike S3 (TASK-4069) evidence and spec §5 (no absolute path, env included).
- [ ] `test_claude_portable_emitters.py::_section` — minimal `ToolkitSection`; bounded by its verified fields.
- [ ] `test_default_emission_unchanged` — toolkit + permission assertions; bounded by AC "default emission unchanged".

---

## Acceptance Criteria

- [ ] `resolve_wikitoolkit_bin` / `resolve_parrot_bin` probe `script_path(root / ".venv", name)`; no `".venv" / "bin"` literal remains in `claude_code/assets.py` (`grep -c '".venv" / "bin"'` → 0).
- [ ] Every emitter listed takes keyword-only `portable: bool = False`; default output is identical to `dev` @ `6c4ca5482` on POSIX (spec §5 "Default host emission … unchanged except the Windows fix").
- [ ] Portable wikitoolkit, toolkit, bookstore entries and the portable hook command contain no absolute path, no `sys.executable`, no `cwd` (spec §5, codex S5).
- [ ] Portable entries are equal for two different roots.
- [ ] `bookstore._is_managed_entry` accepts both managed shapes and rejects foreign ones; `install_bookstore(root, portable=True)` writes the portable entry.
- [ ] Existing suites still pass (see Validation Commands); `ruff check` clean on both modified files.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_claude_portable_emitters.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py -q`
- `pytest tests/knowledge/wiki/test_claude_code_bookstore.py -q`
- `pytest tests/knowledge/wiki/test_installer_toolkit_entries.py -q`
- `pytest tests/knowledge/wiki/test_claude_code.py -q`

---

## Test Specification

See the CREATE block above (`test_claude_portable_emitters.py`): `test_portable_entries_no_abs_paths`,
`test_portable_entries_root_independent`, `test_default_emission_unchanged`,
`test_windows_scripts_branch`, `test_bookstore_managed_detection_accepts_portable`.

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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4081 parrot-installer verified`
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
