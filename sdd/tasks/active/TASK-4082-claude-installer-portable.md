# TASK-4082: Claude host: --portable flag + reconcile that respects portable entries

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4081
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 parts (b), (c) and (e) for **Claude Code**, installer + CLI layer. TASK-4081 gave
every Claude emitter a keyword-only `portable` flag; this task exposes `--portable` on
`parrot claude install`, threads it to the emitters, and fixes the two reconcile paths:

1. `_install_mcp_json` (installer.py:693) — today `if servers.get("wikitoolkit") == entry: … else
   REPLACE` (installer.py:726-731). Spec §7 calls out that this "will silently revert portable
   entries" on the next plain `parrot claude install`.
2. `reconcile_toolkit_entries` (installer.py:616) — called by BOTH `_install_mcp_json` (installer.py:737)
   AND `parrot toolkits` through `mcp/hosts.py::ClaudeAdapter.reconcile` (hosts.py:95-98). It is the
   one place both paths pass through, so the **sticky** rule lives here (no `mcp/hosts.py` edit).

**Mode-resolution rule (decided here; reconciles spec §3 M5(c), §4 and §5):**
- The flag is tri-state: `--portable` → portable, `--no-portable` → baked, *absent* → **keep the
  host's current form** (inferred from the existing managed `wikitoolkit` entry in `.mcp.json`;
  no entry / baked entry → baked). An explicit request always wins and lands exactly the requested
  form (spec §5: "re-running `parrot claude install` (either mode) lands exactly the requested form
  without reverting the other"; §4 `test_portable_transitions_both_ways`). A plain re-install never
  reverts a portable entry (§4 `test_reconcile_respects_portable`). A fresh install without the flag
  is baked, so default emission is unchanged (§5).
- `parrot toolkits` (no flag at all) writes toolkit entries in portable form iff the current managed
  `wikitoolkit` entry is portable (shared brief: "`--portable` is STICKY per host config").
- Spec §3 M5(c)'s literal wording ("keeps an existing entry that matches EITHER form") would make an
  explicit `--portable` over a baked entry a no-op, contradicting §5 — the tri-state rule above is
  the reading that satisfies both §4 tests and §5.
- Ownership is unchanged: the `wikitoolkit` key stays installer-owned exactly as today (a stale
  non-matching entry is still replaced — `test_install_updates_stale_entry`,
  `packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py:63`, must keep passing);
  foreign `parrot-<name>` keys are still warned-and-skipped.

Windows (codex S4): three `PurePosixPath(...).name` call sites (installer.py:151, :590, :877/879)
mis-handle `C:\…\Scripts\parrot.exe`; they move to a separator- and `.exe`-agnostic basename helper.

---

## Scope

- Add `_script_basename(command: str) -> str` and use it at installer.py:151, :590-591, :877, :879.
- Add `_is_portable_wikitoolkit_entry(entry: Any) -> bool` and `_current_portable_mode(root: Path) -> bool`.
- `_is_managed_toolkit_entry`: accept the portable shape (bare `parrot`, `--config
  .parrot/mcp-toolkits.yaml` = `assets.PORTABLE_TOOLKIT_CONFIG`).
- `reconcile_toolkit_entries(root, *, portable: Optional[bool] = None)` — `None` infers (sticky).
- `_install_mcp_json(root, *, portable: bool = False)` — emits the requested form, passes the
  resolved mode to `reconcile_toolkit_entries`.
- `_hook_entry`, `_install_settings_hook`, `_install_permissions` gain `*, portable: bool = False`.
- `install_claude_integration(…, portable: Optional[bool] = None)` resolves the mode once, before
  any write, and threads it to the settings hook, permissions, `.mcp.json`, and `install_bookstore`.
- `parrot claude install --portable/--no-portable` (default unset).
- Write `packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py`.

**NOT in scope**:
- Emitter bodies in `claude_code/assets.py` / `claude_code/bookstore.py` — TASK-4081.
- `mcp/hosts.py` — unchanged: `ClaudeAdapter.reconcile` calls `reconcile_toolkit_entries(root)`
  without a mode, which is exactly the sticky-inference path.
- `uninstall_claude_integration` (its `permission_rules(root)` call at installer.py:1144 stays — it
  removes the baked rule variant if present, harmless in portable mode).
- The git post-commit/post-merge hooks (`.git/hooks/` is never committed; stays baked).
- Codex / Google — TASK-4083 / TASK-4084.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | MODIFY | Tri-state portable resolution, sticky toolkit reconcile, portable-aware managed detection, Windows-safe basenames |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py` | MODIFY | `--portable/--no-portable` on `parrot claude install` |
| `packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py` | CREATE | Transitions, stickiness, default-unchanged, no-abs-path, foreign-untouched, Windows basenames |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (branch `dev` @ `6c4ca5482`, 2026-10-05).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.knowledge.wiki.claude_code import assets                     # installer.py:33 (already imported)
from parrot.knowledge.wiki.claude_code.installer import (                # test-side imports
    install_claude_integration, reconcile_toolkit_entries, _is_managed_toolkit_entry, _is_our_command,
)
from parrot.knowledge.wiki.claude_code.cli import claude                 # cli.py:49 (click group)
from parrot.mcp.toolkit_config import load_toolkits_config               # mcp/toolkit_config.py:90 (installer.py:642 lazy import)
# Created by TASK-4081 (dependency):
#   assets.mcp_json_entry(root, *, portable=False) / assets.toolkit_mcp_json_entry(root, name, section, *, portable=False)
#   assets.hook_command(root, *, portable=False) / assets.permission_rules(root, *, portable=False)
#   assets.PORTABLE_TOOLKIT_CONFIG == ".parrot/mcp-toolkits.yaml"
#   bookstore.install_bookstore(root, *, portable=False)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
from pathlib import Path, PurePosixPath                                   # line 30
def _hook_entry(root: Path) -> dict[str, Any]:                            # line 109; "command": assets.hook_command(root) line 121
def _is_our_command(command: Any) -> bool:                                # line 128; PurePosixPath(token).name check line 151
def _install_settings_hook(root: Path) -> str:                            # line 189; resolved_cmd = assets.hook_command(root) line 205; pre.append(_hook_entry(root)) line 246
def _install_permissions(root: Path) -> list[str]:                        # line 251; all_rules = assets.permission_rules(root) line 293 (2nd occurrence line 1144 is uninstall — leave)
def _is_managed_toolkit_entry(entry: Any, root: Path, name: str) -> bool: # line 574; bin_name = PurePosixPath(assets.resolve_parrot_bin(root)).name line 590; endswith line 591; is_absolute line 607
def reconcile_toolkit_entries(root: Path) -> tuple[list[str], list[str]]: # line 616; toolkit_entry = assets.toolkit_mcp_json_entry(...) line 655
def _install_mcp_json(root: Path) -> str:                                 # line 693; entry = assets.mcp_json_entry(root) line 719; reconcile 726-731; reconcile_toolkit_entries(root) line 737
def _shebang_is_sh_compatible(first_line: str) -> bool:                   # line 863; PurePosixPath(tokens[0]).name line 877; tokens[1] line 879
def install_claude_integration(root, config=None, git_hook=True, gitignore=True, bookstore=True,
                               approve_mcp=True, compaction=False, typesafe_api_key=None,
                               plugin_cli=True) -> list[str]:             # line 964-974
#   save_project_config line 1019; _install_settings_hook line 1022; _install_permissions line 1023;
#   _install_mcp_json line 1024; install_bookstore(root) line 1045

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py
#   "--bookstore/--no-bookstore" option line 76; "--plugin-cli/--no-plugin-cli" line 107;
#   def install(...) line 112, param `plugin_cli: bool,` line 122; call kwarg `plugin_cli=plugin_cli,` line 146

# packages/ai-parrot/src/parrot/mcp/hosts.py — ClaudeAdapter.reconcile (line 95-98) calls
#   reconcile_toolkit_entries(root); ClaudeAdapter.inspect (line 69-93) calls _is_managed_toolkit_entry(entry, root, name)
```

### Does NOT Exist
- ~~a `portable` parameter / `--portable` flag anywhere in `claude_code/installer.py` or `cli.py`~~ — new here.
- ~~a state file recording the chosen mode~~ — forbidden (shared brief: inferred from existing config only).
- ~~`_script_basename`, `_is_portable_wikitoolkit_entry`, `_current_portable_mode`~~ — new private helpers.
- ~~a shared host-adapter path for the wikitoolkit entry~~ — `mcp/hosts.py` reconciles toolkit entries only (spec §6).
- ~~`parrot mcp-local` honouring `PARROT_PROJECT`~~ — it uses `Path.cwd()` (mcp/local_cli.py:183).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_hook_entry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_is_our_command",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_install_settings_hook",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_install_permissions",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_is_managed_toolkit_entry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#reconcile_toolkit_entries",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_install_mcp_json",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_shebang_is_sh_compatible",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#install_claude_integration",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py#install",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py#claude",
    "sym:packages/ai-parrot/src/parrot/mcp/hosts.py#ClaudeAdapter.reconcile",
    "sym:packages/ai-parrot/src/parrot/mcp/hosts.py#ClaudeAdapter.inspect",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#load_toolkits_config"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# installer.py:726-731 — keep this exact equality/replace shape; only the `entry` it compares
# against changes (it is now the REQUESTED form). That alone gives "requested mode wins".
if servers.get("wikitoolkit") == entry:
    wikitoolkit_status = "wikitoolkit entry already current"
else:
    ...
    servers["wikitoolkit"] = entry
```

### Key Constraints
- Resolve the mode ONCE in `install_claude_integration`, **before** `_install_settings_hook`
  writes anything — later steps must not re-infer from a half-written state.
- The portable-vs-baked inference compares the **shape** (`command == "wikitoolkit"` and
  `args == ["mcp"]`), never a resolved path. Known edge: when baked resolution degenerates to the
  bare name (no `.venv`, nothing on PATH) the baked entry is byte-identical to the portable one, so a
  later `parrot toolkits` run infers portable. This is accepted (the two forms are then genuinely
  indistinguishable) — tests must create `<root>/.venv/bin/wikitoolkit` (or monkeypatch
  `assets.resolve_wikitoolkit_bin`) to get a distinguishable baked entry.
- `_is_managed_toolkit_entry` must stay a superset of today's accepted shapes (pinned absolute
  `--config` inside root, legacy two-arg) and must keep rejecting `--config` outside root.
- After the edits `PurePosixPath` may be unused — drop it from the line-30 import (ruff F401).
- Keep warnings on `sys.stderr` exactly as today (installer.py:664); no new `print`.

### References in Codebase
- `packages/ai-parrot/src/parrot/mcp/hosts.py:58-117` — ClaudeAdapter; proves both CLIs funnel into
  `reconcile_toolkit_entries` / `_is_managed_toolkit_entry` in this file.
- `packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py` — existing behaviour that must hold.

---

## Implementation Blueprint

### Steps (in order)
1. Add the three private helpers after `_remove_marker_block` — *why*: one Windows-safe basename
   rule (codex S4) and one portable-shape rule shared by every call site below.
2. Swap the `PurePosixPath(...).name` uses at :151, :590-591, :877, :879 for `_script_basename` —
   *why*: spec §7 "fix it with the Windows branch, not after".
3. Extend `_is_managed_toolkit_entry` for the portable shape — *why*: otherwise the relative
   `--config` hits `is_absolute()` → foreign, and portable entries are never upgraded or removed.
4. Make `reconcile_toolkit_entries` take `portable: Optional[bool] = None` (infer when None) — *why*:
   STICKY rule; this is the path `parrot toolkits` uses.
5. Thread `portable` through `_install_mcp_json`, `_hook_entry`, `_install_settings_hook`,
   `_install_permissions`, `install_bookstore` — *why*: spec §3 M5(b).
6. Resolve the tri-state in `install_claude_integration` and add the CLI flag — *why*: spec §2 New
   Public Interfaces (`--portable` on `parrot claude install`).
7. Write the tests — *why*: spec §4 `test_reconcile_respects_portable`, `test_portable_transitions_both_ways`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _remove_marker_block(text: str, begin: str, end: str) -> str:' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# AFTER — insert below the end of `_remove_marker_block` (verified: claude_code/installer.py:71-85)


def _script_basename(command: str) -> str:
    """Basename of a command/path token, Windows-safe (codex S4).

    Splits on BOTH separators and drops a trailing ``.exe`` (case-insensitive), so
    ``/r/.venv/bin/parrot``, ``C:\\r\\.venv\\Scripts\\parrot.exe`` and ``parrot`` all give ``parrot``.
    """
    name = command.replace("\\", "/").rsplit("/", 1)[-1]
    return name[:-4] if name.lower().endswith(".exe") else name


def _is_portable_wikitoolkit_entry(entry: Any) -> bool:
    """Whether a ``.mcp.json`` wikitoolkit entry is in the portable (bare-command) form."""
    return (
        isinstance(entry, dict)
        and entry.get("command") == assets.HOOK_BIN_NAME
        and entry.get("args") == ["mcp"]
    )


def _current_portable_mode(root: Path) -> bool:
    """Infer the host's current mode from the managed wikitoolkit entry (FEAT-633, sticky).

    No ``.mcp.json``, unparsable JSON, no entry, or a baked entry all mean ``False``.
    """
    # FILL IN: read root/".mcp.json" leniently (mirror the try/except at installer.py:709-717)
    # and return _is_portable_wikitoolkit_entry(mcpServers.get("wikitoolkit")) — bounded by
    # "no new state file" (shared brief) and never raising on a corrupt file.
    raise NotImplementedError

# occurrences: 1 (verified: grep -c '    return any(PurePosixPath(token).name == assets.HOOK_BIN_NAME for token in tokens)' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — `    return any(PurePosixPath(token).name == assets.HOOK_BIN_NAME for token in tokens)` (verified: claude_code/installer.py:151)
    # shlex (POSIX mode) eats backslashes in an unquoted Windows path, so also test the raw
    # whitespace split (codex S4).
    return any(_script_basename(token) == assets.HOOK_BIN_NAME for token in [*tokens, *text.split()])

# occurrences: 1 (verified: grep -c '    bin_name = PurePosixPath(assets.resolve_parrot_bin(root)).name' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — lines 590-592 starting `    bin_name = PurePosixPath(assets.resolve_parrot_bin(root)).name` (verified: claude_code/installer.py:590-591)
    if not isinstance(command, str) or _script_basename(command) != "parrot":
        return False

# occurrences: 1 (verified: grep -c '        if not config_path.is_absolute():' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — lines 605-608 (verified: claude_code/installer.py:605-607); context:
#     if len(args) >= 4 and args[2] == "--config":
#         config_path = Path(args[3])
#         if not config_path.is_absolute():
#             return False
    if len(args) >= 4 and args[2] == "--config":
        if args[3] == assets.PORTABLE_TOOLKIT_CONFIG:  # portable form (TASK-4081) — ours
            return True
        config_path = Path(args[3])
        if not config_path.is_absolute():
            return False
    # (lines 609-613 unchanged; also add one docstring sentence about the portable shape)

# occurrences: 1 (verified: grep -c 'def reconcile_toolkit_entries(root: Path) -> tuple\[list\[str\], list\[str\]\]:' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — signature line (verified: claude_code/installer.py:616); add to the docstring:
#   "portable: None infers the mode from the current wikitoolkit entry (FEAT-633 sticky rule —
#    the `parrot toolkits` path via mcp/hosts.py::ClaudeAdapter.reconcile); True/False force it."
def reconcile_toolkit_entries(root: Path, *, portable: Optional[bool] = None) -> tuple[list[str], list[str]]:

# occurrences: 1 (verified: grep -c '        toolkit_entry = assets.toolkit_mcp_json_entry(root, name, cfg.toolkits\[name\])' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — (verified: claude_code/installer.py:655); and BEFORE the `for name in sorted(enabled_names):`
#           loop (line 653) insert the inference:
    if portable is None:
        portable = _is_portable_wikitoolkit_entry(servers.get("wikitoolkit"))
    ...
        toolkit_entry = assets.toolkit_mcp_json_entry(root, name, cfg.toolkits[name], portable=portable)
```

```python
# occurrences: 1 (verified: grep -c 'def _install_mcp_json(root: Path) -> str:' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — signature (verified: claude_code/installer.py:693); docstring gains a `portable` Args line
def _install_mcp_json(root: Path, *, portable: bool = False) -> str:

# occurrences: 1 (verified: grep -c '    entry = assets.mcp_json_entry(root)' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — (verified: claude_code/installer.py:719)
    entry = assets.mcp_json_entry(root, portable=portable)
# Lines 726-731 (`    if servers.get("wikitoolkit") == entry:`, occurrences 1) stay textually unchanged —
# comparing against the REQUESTED form is the whole fix.

# occurrences: 1 (verified: grep -c '    toolkit_actions, _warnings = reconcile_toolkit_entries(root)' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — (verified: claude_code/installer.py:737)
    toolkit_actions, _warnings = reconcile_toolkit_entries(root, portable=portable)

# occurrences: 1 (verified: grep -c 'def _hook_entry(root: Path) -> dict\[str, Any\]:' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — signature (:109) and `                "command": assets.hook_command(root),` (:121, occurrences 1)
def _hook_entry(root: Path, *, portable: bool = False) -> dict[str, Any]:
                "command": assets.hook_command(root, portable=portable),

# occurrences: 1 (verified: grep -c 'def _install_settings_hook(root: Path) -> str:' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — signature (:189), `    resolved_cmd = assets.hook_command(root)` (:205, occurrences 1) and
#           `    pre.append(_hook_entry(root))` (:246, occurrences 1)
def _install_settings_hook(root: Path, *, portable: bool = False) -> str:
    resolved_cmd = assets.hook_command(root, portable=portable)
    pre.append(_hook_entry(root, portable=portable))

# occurrences: 1 (verified: grep -c 'def _install_permissions(root: Path) -> list\[str\]:' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — signature (:251) and the FIRST `    all_rules = assets.permission_rules(root)` (occurrences 2:
#           :293 inside _install_permissions — context line above it is
#           `        raise RuntimeError(f"{local_path}: 'permissions.allow' is not a list")`; leave :1144 in uninstall)
def _install_permissions(root: Path, *, portable: bool = False) -> list[str]:
    all_rules = assets.permission_rules(root, portable=portable)

# occurrences: 1 (verified: grep -c '    interpreter = PurePosixPath(tokens\[0\]).name' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — :877 and :879 (`        interpreter = PurePosixPath(tokens[1]).name`, occurrences 1)
    interpreter = _script_basename(tokens[0])
        interpreter = _script_basename(tokens[1])
```

```python
# occurrences: 1 (verified: grep -c '    plugin_cli: bool = True,' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# AFTER — insert below `    plugin_cli: bool = True,` in install_claude_integration's signature (verified: claude_code/installer.py:973)
    portable: Optional[bool] = None,
# Docstring Args addition:
#   portable: ``True`` emits bare launcher commands (committable ``.mcp.json``/settings hook, FEAT-633),
#       ``False`` bakes absolute paths (today's default), ``None`` keeps the host's current form
#       (inferred from the managed wikitoolkit entry; a fresh repo is baked).

# occurrences: 1 (verified: grep -c '    save_project_config(root, config)' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# AFTER — insert below `    save_project_config(root, config)` (verified: claude_code/installer.py:1019)
    if portable is None:
        portable = _current_portable_mode(root)
    logger.debug("claude install: portable=%s", portable)

# REPLACE — the four call sites (each occurrences 1, verified :1022, :1023, :1024, :1045):
    actions.append(_install_settings_hook(root, portable=portable))
    actions.extend(_install_permissions(root, portable=portable))
    actions.append(_install_mcp_json(root, portable=portable))
        actions.extend(install_bookstore(root, portable=portable))
```
**Why this shape**: resolving the tri-state in one place keeps every lower function a plain
`bool` (matching the spec §3 M5 skeleton `_install_mcp_json(root, *, portable: bool = False)`); only
the public entry point and `reconcile_toolkit_entries` (the shared toolkits path) accept `None`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "--plugin-cli/--no-plugin-cli",' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py)
# AFTER — insert a new decorator after the `--plugin-cli/--no-plugin-cli` option block ends (verified: cli.py:106-111),
#         i.e. directly above `def install(` (verified: cli.py:112)
@click.option(
    "--portable/--no-portable",
    default=None,
    help="Emit bare launcher commands (wikitoolkit/parrot/bookstore) with no absolute paths, so the "
    "config can be committed. Default: keep the current form (baked absolute paths on a fresh install).",
)

# occurrences: 1 (verified: grep -c '    plugin_cli: bool,' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py)
# AFTER — `    plugin_cli: bool,` (verified: cli.py:122)
    portable: Optional[bool],

# occurrences: 1 (verified: grep -c '            plugin_cli=plugin_cli,' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py)
# AFTER — `            plugin_cli=plugin_cli,` (verified: cli.py:146)
            portable=portable,
```
**Why**: the shared brief places the flag beside the other install switches; `default=None` is what
makes "absent" distinguishable from `--no-portable`.

### `packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py` (CREATE)
```python
"""FEAT-633 TASK-4082 — `parrot claude install --portable`: transitions, stickiness, reconcile."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.claude_code import assets
from parrot.knowledge.wiki.claude_code.cli import claude
from parrot.knowledge.wiki.claude_code.installer import (
    _is_managed_toolkit_entry,
    _is_our_command,
    install_claude_integration,
    reconcile_toolkit_entries,
)


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """Repo with a project venv so the baked form is distinguishable from the portable one."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".parrot").mkdir()
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    for name in ("wikitoolkit", "parrot"):
        (venv_bin / name).write_text("")
    (tmp_path / ".parrot" / "mcp-toolkits.yaml").write_text(
        "toolkits:\n  bounded-source:\n    class: parrot_tools.tool_optimizations.reader.BoundedSourceToolkit\n    kwargs: {}\n"
    )
    return tmp_path


def _servers(root: Path) -> dict:
    return json.loads((root / ".mcp.json").read_text())["mcpServers"]


def _install(root: Path, portable: bool | None) -> None:
    install_claude_integration(root, git_hook=False, gitignore=False, bookstore=False, portable=portable)


def test_default_install_unchanged(repo_root: Path) -> None:
    _install(repo_root, None)
    assert _servers(repo_root)["wikitoolkit"] == assets.mcp_json_entry(repo_root)


def test_portable_transitions_both_ways(repo_root: Path) -> None:
    """Spec §4: default→portable and portable→default land exactly the requested form."""
    _install(repo_root, True)
    assert _servers(repo_root)["wikitoolkit"] == assets.mcp_json_entry(repo_root, portable=True)
    assert _servers(repo_root)["parrot-bounded-source"]["args"][-1] == assets.PORTABLE_TOOLKIT_CONFIG
    _install(repo_root, False)
    assert _servers(repo_root)["wikitoolkit"] == assets.mcp_json_entry(repo_root)
    assert "cwd" in _servers(repo_root)["parrot-bounded-source"]
    _install(repo_root, True)
    assert _servers(repo_root)["wikitoolkit"] == assets.mcp_json_entry(repo_root, portable=True)


def test_reconcile_respects_portable(repo_root: Path) -> None:
    """Spec §4: a plain re-install and the `parrot toolkits` path keep a portable install portable."""
    _install(repo_root, True)
    _install(repo_root, None)
    assert _servers(repo_root)["wikitoolkit"] == assets.mcp_json_entry(repo_root, portable=True)
    del_servers = _servers(repo_root)
    del_servers.pop("parrot-bounded-source")
    (repo_root / ".mcp.json").write_text(json.dumps({"mcpServers": del_servers}))
    reconcile_toolkit_entries(repo_root)  # what mcp/hosts.py::ClaudeAdapter.reconcile calls
    assert "cwd" not in _servers(repo_root)["parrot-bounded-source"]


def test_portable_install_no_abs_paths(repo_root: Path) -> None:
    _install(repo_root, True)
    text = (repo_root / ".mcp.json").read_text() + (repo_root / ".claude" / "settings.json").read_text()
    assert str(repo_root) not in text
    # FILL IN: walk every string value of both files and assert not os.path.isabs(value) — bounded by spec §5.
    raise NotImplementedError


def test_foreign_toolkit_entry_untouched(repo_root: Path) -> None:
    foreign = {"command": "node", "args": ["server.js"]}
    (repo_root / ".mcp.json").write_text(json.dumps({"mcpServers": {"parrot-bounded-source": foreign}}))
    for mode in (True, False):
        _install(repo_root, mode)
        assert _servers(repo_root)["parrot-bounded-source"] == foreign


def test_windows_paths_detected(repo_root: Path) -> None:
    """codex S4: Windows script paths are recognised as ours."""
    win = {"command": "C:\\r\\.venv\\Scripts\\parrot.exe", "args": ["mcp-local", "x"]}
    assert _is_managed_toolkit_entry(win, repo_root, "x")
    assert _is_our_command("C:\\r\\.venv\\Scripts\\wikitoolkit.exe claude-hook")


def test_cli_portable_flag(repo_root: Path) -> None:
    result = CliRunner().invoke(
        claude, ["install", "--path", str(repo_root), "--no-build", "--no-compaction", "--no-git-hook", "--portable"]
    )
    assert result.exit_code == 0, result.output
    assert _servers(repo_root)["wikitoolkit"] == assets.mcp_json_entry(repo_root, portable=True)
```

### FILL IN checklist
- [ ] `installer.py::_current_portable_mode` — lenient `.mcp.json` read; bounded by "no new state file" and never raising.
- [ ] `test_portable_install_no_abs_paths` — recursive string walk; bounded by spec §5 ("no absolute path in any field").
- [ ] Docstrings for every changed signature (Google style) — bounded by codebase conventions.

---

## Acceptance Criteria

- [ ] `parrot claude install --portable` writes the portable wikitoolkit entry, portable toolkit entries (relative `--config`, no `cwd`), the bare `wikitoolkit claude-hook` settings hook and the portable bookstore entry; nothing it writes contains an absolute path (spec §5).
- [ ] `--no-portable` over a portable install restores the exact baked form, and `--portable` over a baked install the exact portable form (spec §4 `test_portable_transitions_both_ways`; §5 "lands exactly the requested form").
- [ ] `parrot claude install` without the flag keeps the current form; on a fresh repo it is baked and byte-identical to today (spec §4 `test_reconcile_respects_portable`, `test_default_emission_unchanged`).
- [ ] `reconcile_toolkit_entries(root)` (the `parrot toolkits` path, via `mcp/hosts.py`) emits portable toolkit entries iff the current wikitoolkit entry is portable — `mcp/hosts.py` unmodified.
- [ ] Foreign `parrot-<name>` entries stay untouched in both modes; `test_install_updates_stale_entry` still passes.
- [ ] Windows `Scripts\parrot.exe` / `wikitoolkit.exe` commands are recognised as managed (codex S4); no `PurePosixPath(...).name` remains in `claude_code/installer.py`.
- [ ] `ruff check` clean on both modified files.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py -q`
- `pytest tests/knowledge/wiki/test_installer_toolkit_entries.py -q`
- `pytest tests/knowledge/wiki/test_installer_mcp_approval.py -q`
- `pytest tests/knowledge/wiki/test_claude_code.py -q`
- `pytest tests/knowledge/wiki/test_claude_code_bookstore.py -q`

---

## Test Specification

See the CREATE block above: `test_default_install_unchanged`, `test_portable_transitions_both_ways`,
`test_reconcile_respects_portable`, `test_portable_install_no_abs_paths`,
`test_foreign_toolkit_entry_untouched`, `test_windows_paths_detected`, `test_cli_portable_flag`.

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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4082 parrot-installer verified`
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
