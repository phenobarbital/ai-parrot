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

1. `_install_mcp_json` (installer.py:694) — today, after a foreign-entry guard (installer.py:730-732,
   FEAT-569), `if servers.get("wikitoolkit") == entry: … else REPLACE` (installer.py:733-738). Spec §7
   calls out that this "will silently revert portable entries" on the next plain `parrot claude install`.
2. `reconcile_toolkit_entries` (installer.py:617) — called by BOTH `_install_mcp_json` (installer.py:744)
   AND `parrot toolkits` through `mcp/hosts.py::ClaudeAdapter.reconcile` (hosts.py:95-98). It is the
   one place both paths pass through, so the **sticky** rule lives here (no `mcp/hosts.py` edit).

**Mode-resolution rule (decided here; reconciles spec §3 M5(c), §4 and §5):**
- The flag is tri-state: `--portable` → portable, `--no-portable` → baked, *absent* → **keep the
  host's current form** (inferred from the existing managed stdio `wikitoolkit` entry in `.mcp.json`;
  baked entry → baked; http, url-only, absent or foreign entry → inferred from the managed
  `parrot-*` entries, see the C24 / D7 bullet below; no managed `parrot-*` entry either → baked). An explicit request always wins and lands exactly the requested
  form (spec §5: "re-running `parrot claude install` (either mode) lands exactly the requested form
  without reverting the other"; §4 `test_portable_transitions_both_ways`). A plain re-install never
  reverts a portable entry (§4 `test_reconcile_respects_portable`). A fresh install without the flag
  is baked, so default emission is unchanged (§5).
- `parrot toolkits` (no flag at all) writes toolkit entries in portable form iff the mode inferred
  by the same rule is portable (shared brief: "`--portable` is STICKY per host config").
- *[spec rev 0.5 C24]* `--remote` (FEAT-569) composes with `--portable`: `--remote` decides only the
  `wikitoolkit` key. When that entry is http, url-only, absent or foreign, the portable mode is
  inferred from the managed `parrot-*` entries (portable iff `args[3] == assets.PORTABLE_TOOLKIT_CONFIG`).
- Spec §3 M5(c)'s literal wording ("keeps an existing entry that matches EITHER form") would make an
  explicit `--portable` over a baked entry a no-op, contradicting §5 — the tri-state rule above is
  the reading that satisfies both §4 tests and §5.
  *[rev 0.5]* With the flag *absent*, the M5(c) rule now applies to the `wikitoolkit` key: an existing
  entry equal to the baked or the portable managed form is kept as is (that is what keeps a portable
  `wikitoolkit` entry when there is no `parrot-*` entry to infer from).
- Ownership is unchanged from today (FEAT-569, `_is_wikitoolkit_entry`, installer.py:753-762): a
  managed-shape stale `wikitoolkit` entry is replaced (`test_install_updates_stale_entry`,
  `packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py:66`); a foreign `wikitoolkit` entry is
  left untouched (`test_install_leaves_foreign_wikitoolkit_entry_untouched`, same file :75). Both must
  keep passing. Foreign `parrot-<name>` keys are still warned-and-skipped.

Windows (codex S4): three `PurePosixPath(...).name` call sites (installer.py:152, :591, :896/898)
mis-handle `C:\…\Scripts\parrot.exe`; they move to a separator- and `.exe`-agnostic basename helper.

---

## Readiness review — 2026-10-19 (dev 9f51c7735)
- Refreshed against dev 9f51c7735: `claude_code/installer.py` and `cli.py` anchors shifted (6b30156ad `--remote`, 6164b075b ledger hooks); blueprint now keeps the FEAT-569 `remote=` plumbing (`_install_mcp_json` signature, else-branch-only entry replacement, call site, CLI option/param/kwarg positions); ownership text updated for the foreign-entry guard (caaa25f73); two Validation Commands added.
- Resolved by spec rev 0.5 (2026-10-20):
  - C24 Windows — `_is_wikitoolkit_entry` (installer.py:762) now matches the script basename (`.exe` included) via `_script_basename`; added to Scope, Acceptance Criteria and `test_windows_paths_detected`.
  - C24 `--remote` × `--portable` — `--remote` decides only the `wikitoolkit` key; when that entry is http, url-only, absent or foreign, `_current_portable_mode` infers the mode from the managed `parrot-*` entries (`args[3] == assets.PORTABLE_TOOLKIT_CONFIG`), and `reconcile_toolkit_entries` uses it; new test `test_remote_portable_sticky`.
  - C24 / D6 detail (dev 2026-10-20): `_is_wikitoolkit_entry` starts at `claude_code/installer.py:753`; `:762` is the `endswith` line inside it. The http branch is unchanged. The hook-body half of D6 is TASK-4081.
  - C24 / D7 detail (dev 2026-10-20): the mode for everything other than the `wikitoolkit` key (settings hook, permissions, `parrot-*` entries, bookstore) is the explicit flag or, when absent, `_current_portable_mode`: a managed stdio `wikitoolkit` entry decides it; otherwise `_portable_from_servers` (portable iff ANY managed `parrot-*` entry is in portable shape: `--config` == `assets.PORTABLE_TOOLKIT_CONFIG`, no `cwd`; PR #1746 review). The portable `parrot-*` shape check is `_is_portable_toolkit_entry`; `_is_portable_wikitoolkit_entry` keeps checking the `wikitoolkit` shape. Because the existing managed entry is re-emitted in its own form when the flag is absent, a portable install with no `parrot-*` entry stays portable on a plain re-install (no state file, no extra signal).
- Anchors re-verified on dev 2026-10-20: all unchanged (`_install_mcp_json` :694, `entry = assets.mcp_json_entry(root)` :723, foreign guard :730, `elif servers.get("wikitoolkit") == entry:` :733, reconcile range 733-738, `_is_wikitoolkit_entry` :753, `install_claude_integration` :1034).

## Scope

- Add `_script_basename(command: str) -> str` and use it at installer.py:152, :591-592, :896, :898.
- *[spec rev 0.5 C24 / D6]* `_is_wikitoolkit_entry` (installer.py:753-762) matches the script basename
  (`_script_basename(command) == assets.HOOK_BIN_NAME`, so `.exe` counts) instead of
  `command.endswith("wikitoolkit")` (:762). The http branch is unchanged.
- Add `_is_portable_wikitoolkit_entry(entry: Any) -> bool`, `_is_portable_toolkit_entry(entry: Any) -> bool`,
  `_portable_from_servers(servers, root) -> bool` and `_current_portable_mode(root: Path) -> bool`
  (*[spec rev 0.5 C24 / D7]* http, url-only, absent or foreign `wikitoolkit` entry → mode inferred from the
  managed `parrot-*` entries).
- `_is_managed_toolkit_entry`: accept the portable shape (bare `parrot`, `--config
  .parrot/mcp-toolkits.yaml` = `assets.PORTABLE_TOOLKIT_CONFIG`).
- `reconcile_toolkit_entries(root, *, portable: Optional[bool] = None)` — `None` infers (sticky) via
  `_current_portable_mode(root)`.
- `_install_mcp_json(root, *, remote=None, portable: bool = False)` — keeps the FEAT-569 `remote`
  branch as is, emits the requested stdio form otherwise, passes the resolved mode to
  `reconcile_toolkit_entries`. With the flag absent an existing managed stdio `wikitoolkit` entry is
  re-emitted in its own form (the mode is read from it), so it stays as is (spec §3 M5(c)).
- `_hook_entry`, `_install_settings_hook`, `_install_permissions` gain `*, portable: bool = False`.
- `install_claude_integration(…, portable: Optional[bool] = None)` resolves the mode once, before
  any write, and threads it to the settings hook, permissions, `.mcp.json`, and `install_bookstore`.
- `parrot claude install --portable/--no-portable` (default unset).
- Write `packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py`.

**NOT in scope**:
- Emitter bodies in `claude_code/assets.py` / `claude_code/bookstore.py` — TASK-4081.
- `mcp/hosts.py` — unchanged: `ClaudeAdapter.reconcile` calls `reconcile_toolkit_entries(root)`
  without a mode, which is exactly the sticky-inference path.
- `uninstall_claude_integration` (its `permission_rules(root)` call at installer.py:1218 stays — it
  removes the baked rule variant if present, harmless in portable mode).
- The git post-commit/post-merge hooks (`.git/hooks/` is never committed; stays baked; their C24
  quoting is TASK-4081).
- Codex / Google — TASK-4083 / TASK-4084.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | MODIFY | Tri-state portable resolution (C24: `parrot-*` inference when the `wikitoolkit` entry is remote/absent/foreign), sticky toolkit reconcile, portable-aware managed detection, Windows-safe basenames incl. `_is_wikitoolkit_entry` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py` | MODIFY | `--portable/--no-portable` on `parrot claude install` |
| `packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py` | CREATE | Transitions, stickiness, default-unchanged, no-abs-path, foreign-untouched, Windows basenames, `--remote` × `--portable` stickiness |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (branch `dev` @ `6c4ca5482`, 2026-10-05; line anchors refreshed against `9f51c7735`, 2026-10-19).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.knowledge.wiki.claude_code import assets                     # installer.py:33 (already imported)
from parrot.knowledge.wiki.claude_code.installer import (                # test-side imports
    install_claude_integration, reconcile_toolkit_entries, _is_managed_toolkit_entry, _is_our_command,
    _is_wikitoolkit_entry,                                                # installer.py:753 (FEAT-569)
)
from parrot.knowledge.wiki.claude_code.cli import claude                 # cli.py:49 (click group)
from parrot.mcp.toolkit_config import load_toolkits_config               # mcp/toolkit_config.py:90 (installer.py:643 lazy import)
from parrot.knowledge.wiki.project import WikiRemoteConfig                # installer.py:37 (already imported, FEAT-569)
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
def _hook_entry(root: Path) -> dict[str, Any]:                            # line 110; "command": assets.hook_command(root) line 122
def _is_our_command(command: Any) -> bool:                                # line 129; PurePosixPath(token).name check line 152
def _install_settings_hook(root: Path) -> str:                            # line 190; resolved_cmd = assets.hook_command(root) line 206; pre.append(_hook_entry(root)) line 247
def _install_permissions(root: Path) -> list[str]:                        # line 252; all_rules = assets.permission_rules(root) line 294 (2nd occurrence line 1218 is uninstall — leave)
def _is_managed_toolkit_entry(entry: Any, root: Path, name: str) -> bool: # line 575; bin_name = PurePosixPath(assets.resolve_parrot_bin(root)).name line 591; endswith line 592; is_absolute line 608
def reconcile_toolkit_entries(root: Path) -> tuple[list[str], list[str]]: # line 617; toolkit_entry = assets.toolkit_mcp_json_entry(...) line 656
def _install_mcp_json(root: Path, *, remote: Optional[WikiRemoteConfig] = None) -> str:  # line 694 (FEAT-569)
#   if remote is not None: entry = assets.mcp_json_entry_remote(...) line 720-721; else: entry = assets.mcp_json_entry(root) line 723;
#   foreign guard (not _is_wikitoolkit_entry) line 730-732; equality/replace 733-738; reconcile_toolkit_entries(root) line 744
def _is_wikitoolkit_entry(entry: Any) -> bool:                            # line 753-762 (stdio + http managed shapes; stdio uses command.endswith("wikitoolkit") at line 762 — [rev 0.5] D6: becomes _script_basename(command) == "wikitoolkit")
def _shebang_is_sh_compatible(first_line: str) -> bool:                   # line 882; PurePosixPath(tokens[0]).name line 896; tokens[1] line 898
def install_claude_integration(root, config=None, git_hook=True, gitignore=True, bookstore=True,
                               approve_mcp=True, compaction=False, typesafe_api_key=None,
                               plugin_cli=True, remote=None) -> list[str]:  # line 1034-1045
#   save_project_config line 1092; _install_settings_hook line 1095; _install_permissions line 1096;
#   _install_mcp_json(root, remote=remote) line 1097; install_bookstore(root) line 1119

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py
#   "--bookstore/--no-bookstore" option line 76; "--plugin-cli/--no-plugin-cli" line 107;
#   "--remote" / "--remote-url" / "--token-env" options lines 112-125 (FEAT-569);
#   def install(...) line 126, param `plugin_cli: bool,` line 136, `token_env: Optional[str],` line 139;
#   call kwargs `plugin_cli=plugin_cli,` line 175, `remote=remote,` line 176

# packages/ai-parrot/src/parrot/mcp/hosts.py — ClaudeAdapter.reconcile (line 95-98) calls
#   reconcile_toolkit_entries(root); ClaudeAdapter.inspect (line 69-93) calls _is_managed_toolkit_entry(entry, root, name)
```

### Does NOT Exist
- ~~a `portable` parameter / `--portable` flag anywhere in `claude_code/installer.py` or `cli.py`~~ — new here.
- ~~a state file recording the chosen mode~~ — forbidden (shared brief: inferred from existing config only).
- ~~`_script_basename`, `_is_portable_wikitoolkit_entry`, `_is_portable_toolkit_entry`, `_portable_from_servers`, `_current_portable_mode`~~ — new private helpers *[rev 0.5]*.
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
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_is_wikitoolkit_entry",
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
# installer.py:730-738 — keep this exact foreign-guard + equality/replace shape; only the `entry` it
# compares against changes (it is now the REQUESTED form). That alone gives "requested mode wins".
if "wikitoolkit" in servers and not _is_wikitoolkit_entry(servers["wikitoolkit"]):
    ...  # foreign — left untouched (FEAT-569)
elif servers.get("wikitoolkit") == entry:
    wikitoolkit_status = "wikitoolkit entry already current"
else:
    ...
    servers["wikitoolkit"] = entry
```

### Key Constraints
- Resolve the mode ONCE in `install_claude_integration`, **before** `_install_settings_hook`
  writes anything — later steps must not re-infer from a half-written state.
- *[rev 0.5]* D7: the portable-vs-baked inference compares the **shape** of the managed `parrot-*`
  entries (relative `--config` == `assets.PORTABLE_TOOLKIT_CONFIG`, no `cwd`), never a resolved path and
  never the `wikitoolkit` entry. A baked toolkit entry always carries an absolute `--config` and `cwd`,
  so the two forms stay distinguishable even when `resolve_parrot_bin` degenerates to bare `parrot`.
  For the M5(c) keep rule, tests still create `<root>/.venv/bin/wikitoolkit` so the baked and portable
  `wikitoolkit` entries differ.
- `_is_managed_toolkit_entry` must stay a superset of today's accepted shapes (pinned absolute
  `--config` inside root, legacy two-arg) and must keep rejecting `--config` outside root.
- After the edits `PurePosixPath` may be unused — drop it from the line-30 import (ruff F401).
- Keep warnings on `sys.stderr` exactly as today (installer.py:665, :731); no new `print`.
- `--remote` (FEAT-569) keeps its own `wikitoolkit` entry: `portable` only changes the stdio
  (else) branch of `_install_mcp_json`; every call that passes `remote=remote` today keeps it.
- *[spec rev 0.5 C24]* `--remote` decides only the `wikitoolkit` key; when that entry is http,
  url-only, absent or foreign, the mode comes from the managed `parrot-*` entries.
  **Resolved (PR #1746 review, 2026-10-20)**: if **any** managed `parrot-*` entry is portable, the
  mode is portable, because the user opted in at some point and the mode is sticky; the reconcile then
  rewrites every managed entry in that mode. With no managed `parrot-*` entry the mode is baked, so a fresh
  install stays baked (spec default).
  *[rev 0.5 D7]* With `--remote`, the settings hook, permissions, `parrot-*` entries and bookstore still
  follow the resolved mode, and an http `wikitoolkit` entry never changes that mode.

### References in Codebase
- `packages/ai-parrot/src/parrot/mcp/hosts.py:58-117` — ClaudeAdapter; proves both CLIs funnel into
  `reconcile_toolkit_entries` / `_is_managed_toolkit_entry` in this file.
- `packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py` — existing behaviour that must hold.

---

## Implementation Blueprint

### Steps (in order)
1. Add the private helpers after `_remove_marker_block` (*[rev 0.5]* five: `_script_basename`,
   `_is_portable_wikitoolkit_entry`, `_is_portable_toolkit_entry`, `_portable_from_servers`, `_current_portable_mode`) — *why*: one Windows-safe basename
   rule (codex S4) and one portable-shape rule shared by every call site below.
2. Swap the `PurePosixPath(...).name` uses at :152, :591-592, :896, :898 for `_script_basename` —
   *why*: spec §7 "fix it with the Windows branch, not after". Same for the
   `command.endswith("wikitoolkit")` check in `_is_wikitoolkit_entry` (:762) — *why*: spec rev 0.5 C24.
3. Extend `_is_managed_toolkit_entry` for the portable shape — *why*: otherwise the relative
   `--config` hits `is_absolute()` → foreign, and portable entries are never upgraded or removed.
4. Make `reconcile_toolkit_entries` take `portable: Optional[bool] = None` (infer when None) — *why*:
   STICKY rule; this is the path `parrot toolkits` uses.
5. Thread `portable` through `_install_mcp_json`, `_hook_entry`, `_install_settings_hook`,
   `_install_permissions`, `install_bookstore` — *why*: spec §3 M5(b).
6. Resolve the tri-state in `install_claude_integration` and add the CLI flag — *why*: spec §2 New
   Public Interfaces (`--portable` on `parrot claude install`).
7. Write the tests — *why*: spec §4 `test_reconcile_respects_portable`, `test_portable_transitions_both_ways`.
8. *[rev 0.5]* D6: `_is_wikitoolkit_entry` stdio match via `_script_basename` (:762) — *why*: a Windows entry must not be foreign.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _remove_marker_block(text: str, begin: str, end: str) -> str:' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# AFTER — insert below the end of `_remove_marker_block` (verified: claude_code/installer.py:72-86)


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


def _is_portable_toolkit_entry(entry: Any) -> bool:  # [rev 0.5] D7 — the parrot-* shape
    """Whether a managed ``parrot-<name>`` entry is in the portable form (relative config, no cwd)."""
    args = entry.get("args") if isinstance(entry, dict) else None
    return (
        isinstance(args, list)
        and len(args) >= 4
        and args[2] == "--config"
        and args[3] == assets.PORTABLE_TOOLKIT_CONFIG
        and "cwd" not in entry
    )


def _portable_from_servers(servers: dict[str, Any], root: Path) -> bool:  # [rev 0.5] D7 sub-step
    """Portable iff ANY managed ``parrot-*`` entry is portable (PR #1746 review: the mode is sticky).

    Used only when the ``wikitoolkit`` key cannot decide (http, url-only, absent or foreign); no managed
    ``parrot-*`` entry → ``False``.
    """
    managed = [
        entry for key, entry in servers.items()
        if key.startswith("parrot-") and _is_managed_toolkit_entry(entry, root, key[len("parrot-"):])
    ]
    return any(_is_portable_toolkit_entry(entry) for entry in managed)


def _current_portable_mode(root: Path) -> bool:
    """Infer the host's current mode (FEAT-633, sticky).

    A managed stdio ``wikitoolkit`` entry decides it directly (baked → ``False``). When that entry
    is http, url-only, absent or foreign (spec rev 0.5 C24 / D7 — ``--remote`` decides only that key),
    the mode is inferred from the managed ``parrot-*`` entries. No ``.mcp.json`` or unparsable
    JSON mean ``False``.
    """
    # FILL IN: read root/".mcp.json" leniently (mirror the try/except at installer.py:710-718).
    # If mcpServers["wikitoolkit"] is a managed stdio entry (_is_wikitoolkit_entry and no "type"/"url"),
    # return _is_portable_wikitoolkit_entry(it); otherwise return _portable_from_servers(mcpServers, root)
    # — bounded by spec rev 0.5 C24 / D7, "no new state file" (shared brief) and never raising
    # on a corrupt file. Mixed managed entries → portable if ANY is portable; none → False (Key Constraints, resolved).
    raise NotImplementedError

# occurrences: 1 (verified: grep -c '    return any(PurePosixPath(token).name == assets.HOOK_BIN_NAME for token in tokens)' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — `    return any(PurePosixPath(token).name == assets.HOOK_BIN_NAME for token in tokens)` (verified: claude_code/installer.py:152)
    # shlex (POSIX mode) eats backslashes in an unquoted Windows path, so also test the raw
    # whitespace split (codex S4).
    return any(_script_basename(token) == assets.HOOK_BIN_NAME for token in [*tokens, *text.split()])

# occurrences: 1 (verified: grep -c '    return isinstance(command, str) and command.endswith("wikitoolkit") and entry.get("args") == \["mcp"\]' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — last line of `_is_wikitoolkit_entry` (verified: claude_code/installer.py:762); spec rev 0.5 C24:
#           match the script basename so `.exe` counts. Also update its docstring (:754, "ends with wikitoolkit").
    return isinstance(command, str) and _script_basename(command) == assets.HOOK_BIN_NAME and entry.get("args") == ["mcp"]

# occurrences: 1 (verified: grep -c '    bin_name = PurePosixPath(assets.resolve_parrot_bin(root)).name' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — lines 591-593 starting `    bin_name = PurePosixPath(assets.resolve_parrot_bin(root)).name` (verified: claude_code/installer.py:591-592)
    if not isinstance(command, str) or _script_basename(command) != "parrot":
        return False

# occurrences: 1 (verified: grep -c '        if not config_path.is_absolute():' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — lines 606-609 (verified: claude_code/installer.py:606-608); context:
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
    # (lines 610-614 unchanged; also add one docstring sentence about the portable shape)

# occurrences: 1 (verified: grep -c 'def reconcile_toolkit_entries(root: Path) -> tuple\[list\[str\], list\[str\]\]:' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — signature line (verified: claude_code/installer.py:617); add to the docstring:
#   "portable: None infers the mode via _current_portable_mode (FEAT-633 sticky rule, spec rev 0.5
#    C24 / D7 — the `parrot toolkits` path via mcp/hosts.py::ClaudeAdapter.reconcile); True/False force it."
def reconcile_toolkit_entries(root: Path, *, portable: Optional[bool] = None) -> tuple[list[str], list[str]]:

# occurrences: 1 (verified: grep -c '        toolkit_entry = assets.toolkit_mcp_json_entry(root, name, cfg.toolkits\[name\])' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — (verified: claude_code/installer.py:656); and BEFORE the `for name in sorted(enabled_names):`
#           loop (line 654) insert the inference:
    if portable is None:
        portable = _current_portable_mode(root)  # reads .mcp.json before this function writes it
    ...
        toolkit_entry = assets.toolkit_mcp_json_entry(root, name, cfg.toolkits[name], portable=portable)
```

```python
# occurrences: 1 (verified: grep -c 'def _install_mcp_json(root: Path, \*, remote: Optional\[WikiRemoteConfig\] = None) -> str:' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — signature (verified: claude_code/installer.py:694); keep `remote` (FEAT-569); docstring gains a `portable` Args line
def _install_mcp_json(root: Path, *, remote: Optional[WikiRemoteConfig] = None, portable: bool = False) -> str:

# occurrences: 1 (verified: grep -c '        entry = assets.mcp_json_entry(root)' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — the ELSE-branch line only (8-space indent, verified: claude_code/installer.py:723); the
#           `if remote is not None:` branch (:720-721, `assets.mcp_json_entry_remote(...)`) stays unchanged
        entry = assets.mcp_json_entry(root, portable=portable)
# Lines 730-738 (foreign guard `    if "wikitoolkit" in servers and not _is_wikitoolkit_entry(...)` and
# `    elif servers.get("wikitoolkit") == entry:`, occurrences 1) stay textually unchanged —
# comparing against the REQUESTED form is the whole fix.

# occurrences: 1 (verified: grep -c '    toolkit_actions, _warnings = reconcile_toolkit_entries(root)' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — (verified: claude_code/installer.py:744)
    toolkit_actions, _warnings = reconcile_toolkit_entries(root, portable=portable)

# occurrences: 1 (verified: grep -c 'def _hook_entry(root: Path) -> dict\[str, Any\]:' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — signature (:110) and `                "command": assets.hook_command(root),` (:122, occurrences 1)
def _hook_entry(root: Path, *, portable: bool = False) -> dict[str, Any]:
                "command": assets.hook_command(root, portable=portable),

# occurrences: 1 (verified: grep -c 'def _install_settings_hook(root: Path) -> str:' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — signature (:190), `    resolved_cmd = assets.hook_command(root)` (:206, occurrences 1) and
#           `    pre.append(_hook_entry(root))` (:247, occurrences 1)
def _install_settings_hook(root: Path, *, portable: bool = False) -> str:
    resolved_cmd = assets.hook_command(root, portable=portable)
    pre.append(_hook_entry(root, portable=portable))

# occurrences: 1 (verified: grep -c 'def _install_permissions(root: Path) -> list\[str\]:' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — signature (:252) and the FIRST `    all_rules = assets.permission_rules(root)` (occurrences 2:
#           :294 inside _install_permissions — two lines above it (:292) is the first of two
#           `        raise RuntimeError(f"{local_path}: 'permissions.allow' is not a list")`; leave :1218 in uninstall)
def _install_permissions(root: Path, *, portable: bool = False) -> list[str]:
    all_rules = assets.permission_rules(root, portable=portable)

# [rev 0.5] D6 — occurrences: 1 (verified: grep -c '    return isinstance(command, str) and command.endswith("wikitoolkit") and entry.get("args") == \["mcp"\]' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — (verified: claude_code/installer.py:762, inside _is_wikitoolkit_entry :753); also fix its docstring ("basename is wikitoolkit")
    return isinstance(command, str) and _script_basename(command) == "wikitoolkit" and entry.get("args") == ["mcp"]

# occurrences: 1 (verified: grep -c '    interpreter = PurePosixPath(tokens\[0\]).name' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE — :896 and :898 (`        interpreter = PurePosixPath(tokens[1]).name`, occurrences 1)
    interpreter = _script_basename(tokens[0])
        interpreter = _script_basename(tokens[1])
```

```python
# occurrences: 1 (verified: grep -c '    remote: Optional\[WikiRemoteConfig\] = None,' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# AFTER — insert below `    remote: Optional[WikiRemoteConfig] = None,` in install_claude_integration's signature
#         (verified: claude_code/installer.py:1044; it follows `    plugin_cli: bool = True,` at :1043)
    portable: Optional[bool] = None,
# Docstring Args addition:
#   portable: ``True`` emits bare launcher commands (committable ``.mcp.json``/settings hook, FEAT-633),
#       ``False`` bakes absolute paths (today's default), ``None`` keeps the host's current form
#       (from the managed stdio ``wikitoolkit`` entry, else the managed ``parrot-*`` entries — [rev 0.5] C24 / D7;
#       a fresh repo is baked).

# occurrences: 1 (verified: grep -c '    save_project_config(root, config)' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# AFTER — insert below `    save_project_config(root, config)` (verified: claude_code/installer.py:1092)
    if portable is None:
        portable = _current_portable_mode(root)  # [rev 0.5] C24 / D7 — wikitoolkit stdio entry, else parrot-* entries
    logger.debug("claude install: portable=%s", portable)

# REPLACE — the four call sites (each occurrences 1, verified :1095, :1096, :1097, :1119); the
#           `.mcp.json` call already passes `remote=remote` (FEAT-569) — keep it:
    actions.append(_install_settings_hook(root, portable=portable))
    actions.extend(_install_permissions(root, portable=portable))
    actions.append(_install_mcp_json(root, remote=remote, portable=portable))
        actions.extend(install_bookstore(root, portable=portable))
```
**Why this shape**: resolving the tri-state in one place keeps every lower function a plain
`bool` (matching the spec §3 M5 skeleton `_install_mcp_json(root, *, portable: bool = False)`); only
the public entry point and `reconcile_toolkit_entries` (the shared toolkits path) accept `None`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "--token-env",' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py)
# AFTER — insert a new decorator after the `--token-env` option block ends (verified: cli.py:121-125, the last of
#         the FEAT-569 `--remote`/`--remote-url`/`--token-env` options), i.e. directly above `def install(` (verified: cli.py:126)
@click.option(
    "--portable/--no-portable",
    default=None,
    help="Emit bare launcher commands (wikitoolkit/parrot/bookstore) with no absolute paths, so the "
    "config can be committed. Default: keep the current form (baked absolute paths on a fresh install).",
    # [rev 0.5] D7: "current form" = the managed parrot-* entries; --remote does not change it.
)

# occurrences: 1 (verified: grep -c '    token_env: Optional\[str\],' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py)
# AFTER — `    token_env: Optional[str],` (verified: cli.py:139)
    portable: Optional[bool],

# occurrences: 1 (verified: grep -c '            remote=remote,' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py)
# AFTER — `            remote=remote,` (verified: cli.py:176)
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
    _is_wikitoolkit_entry,  # [rev 0.5] D6
    install_claude_integration,
    reconcile_toolkit_entries,
)
from parrot.knowledge.wiki.project import WikiRemoteConfig  # [rev 0.5] D7


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


def _install(root: Path, portable: bool | None, remote: WikiRemoteConfig | None = None) -> None:  # [rev 0.5] remote
    install_claude_integration(
        root, git_hook=False, gitignore=False, bookstore=False, portable=portable, remote=remote
    )


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
    # [rev 0.5] D7: a toolkit enabled later follows the existing portable parrot-* entries
    cfg = repo_root / ".parrot" / "mcp-toolkits.yaml"
    cfg.write_text(cfg.read_text() + "  reader:\n    class: parrot_tools.tool_optimizations.reader.BoundedSourceToolkit\n    kwargs: {}\n")
    reconcile_toolkit_entries(repo_root)  # what mcp/hosts.py::ClaudeAdapter.reconcile calls
    assert "cwd" not in _servers(repo_root)["parrot-reader"]


def test_plain_reinstall_keeps_portable_wikitoolkit_without_toolkits(repo_root: Path) -> None:
    """[rev 0.5] spec §3 M5(c): with no parrot-* entry, the managed stdio wikitoolkit entry decides the mode and is kept."""
    (repo_root / ".parrot" / "mcp-toolkits.yaml").write_text("toolkits: {}\n")
    _install(repo_root, True)
    _install(repo_root, None)
    assert _servers(repo_root)["wikitoolkit"] == assets.mcp_json_entry(repo_root, portable=True)


def test_remote_does_not_reset_portable_mode(repo_root: Path) -> None:
    """[rev 0.5] D7: --remote decides only the wikitoolkit key; an http entry cannot decide, so the mode comes from the parrot-* entries."""
    _install(repo_root, True)
    _install(repo_root, None, remote=WikiRemoteConfig(url="https://h/mcp/w", token_env="WT"))
    assert _servers(repo_root)["wikitoolkit"]["type"] == "http"
    assert "cwd" not in _servers(repo_root)["parrot-bounded-source"]
    settings = (repo_root / ".claude" / "settings.json").read_text()
    assert assets.hook_command(repo_root, portable=True) in settings and str(repo_root) not in settings
    reconcile_toolkit_entries(repo_root)
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
    # spec rev 0.5 C24: _is_wikitoolkit_entry matches the script basename, `.exe` included
    assert _is_wikitoolkit_entry({"command": "C:\\r\\.venv\\Scripts\\wikitoolkit.exe", "args": ["mcp"]})


def test_remote_portable_sticky(repo_root: Path) -> None:
    """Spec rev 0.5 C24: --remote decides only the wikitoolkit key; the mode comes from the parrot-* entries."""
    remote = WikiRemoteConfig(url="https://h/mcp/w", token_env="WT")
    kwargs = {"git_hook": False, "gitignore": False, "bookstore": False, "remote": remote}
    install_claude_integration(repo_root, portable=True, **kwargs)
    assert _servers(repo_root)["wikitoolkit"] == assets.mcp_json_entry_remote(remote.url, remote.token_env)
    assert _servers(repo_root)["parrot-bounded-source"]["args"][-1] == assets.PORTABLE_TOOLKIT_CONFIG
    install_claude_integration(repo_root, **kwargs)  # flag absent → keep portable (http wikitoolkit entry)
    assert "cwd" not in _servers(repo_root)["parrot-bounded-source"]
    assert str(repo_root) not in (repo_root / ".claude" / "settings.json").read_text()
    with (repo_root / ".parrot" / "mcp-toolkits.yaml").open("a") as fh:  # a toolkit added later by `parrot toolkits`
        fh.write("  bounded-source-2:\n    class: parrot_tools.tool_optimizations.reader.BoundedSourceToolkit\n    kwargs: {}\n")
    reconcile_toolkit_entries(repo_root)  # the mcp/hosts.py::ClaudeAdapter.reconcile path
    assert _servers(repo_root)["parrot-bounded-source-2"]["args"][-1] == assets.PORTABLE_TOOLKIT_CONFIG


def test_windows_wikitoolkit_entry_is_managed() -> None:
    """[rev 0.5] D6: basename match without .exe; a different basename stays foreign."""
    assert _is_wikitoolkit_entry({"command": "C:\\r\\.venv\\Scripts\\wikitoolkit.exe", "args": ["mcp"]})
    assert _is_wikitoolkit_entry({"command": "/r/.venv/bin/wikitoolkit", "args": ["mcp"]})
    assert not _is_wikitoolkit_entry({"command": "/r/bin/my-wikitoolkit", "args": ["mcp"]})


def test_cli_portable_flag(repo_root: Path) -> None:
    result = CliRunner().invoke(
        claude, ["install", "--path", str(repo_root), "--no-build", "--no-compaction", "--no-git-hook", "--portable"]
    )
    assert result.exit_code == 0, result.output
    assert _servers(repo_root)["wikitoolkit"] == assets.mcp_json_entry(repo_root, portable=True)
```

### FILL IN checklist
- [ ] `installer.py::_current_portable_mode` — lenient `.mcp.json` read, `parrot-*` inference (`_portable_from_servers`) for an http/url-only/absent/foreign `wikitoolkit` entry; bounded by spec rev 0.5 C24 / D7, "no new state file" and never raising.
- [ ] `test_portable_install_no_abs_paths` — recursive string walk; bounded by spec §5 ("no absolute path in any field").
- [ ] Docstrings for every changed signature (Google style) — bounded by codebase conventions.

---

## Acceptance Criteria

- [ ] `parrot claude install --portable` writes the portable wikitoolkit entry, portable toolkit entries (relative `--config`, no `cwd`), the bare `wikitoolkit claude-hook` settings hook and the portable bookstore entry; nothing it writes contains an absolute path (spec §5).
- [ ] `--no-portable` over a portable install restores the exact baked form, and `--portable` over a baked install the exact portable form (spec §4 `test_portable_transitions_both_ways`; §5 "lands exactly the requested form").
- [ ] `parrot claude install` without the flag keeps the current form; on a fresh repo it is baked and byte-identical to today (spec §4 `test_reconcile_respects_portable`, `test_default_emission_unchanged`).
- [ ] `reconcile_toolkit_entries(root)` (the `parrot toolkits` path, via `mcp/hosts.py`) emits portable toolkit entries iff the inferred mode is portable — `mcp/hosts.py` unmodified.
- [ ] *[spec rev 0.5 C24]* `--remote` decides only the `wikitoolkit` key: when that entry is http, url-only, absent or foreign, the mode is inferred from the managed `parrot-*` entries, so `--remote --portable` followed by a plain `--remote` re-install or `parrot toolkits` stays portable (`test_remote_portable_sticky`).
- [ ] *[rev 0.5]* Without the flag, an existing managed stdio `wikitoolkit` entry in either form is kept as is, even with no `parrot-*` entry to infer from (`test_plain_reinstall_keeps_portable_wikitoolkit_without_toolkits`).
- [ ] *[rev 0.5 D7]* `--remote` without `--portable/--no-portable` over a portable install keeps the hook, permissions and `parrot-*` entries portable (`test_remote_does_not_reset_portable_mode`).
- [ ] *[rev 0.5 D6]* `_is_wikitoolkit_entry` accepts `C:\…\Scripts\wikitoolkit.exe` (basename without `.exe`) and rejects other basenames (`test_windows_wikitoolkit_entry_is_managed`).
- [ ] Foreign `parrot-<name>` entries stay untouched in both modes; `test_install_updates_stale_entry` and `test_install_leaves_foreign_wikitoolkit_entry_untouched` still pass; `--remote` (FEAT-569) behaviour is unchanged.
- [ ] Windows `Scripts\parrot.exe` / `wikitoolkit.exe` commands are recognised as managed (codex S4), including by `_is_wikitoolkit_entry` (spec rev 0.5 C24: script basename, `.exe` included); no `PurePosixPath(...).name` and no `command.endswith("wikitoolkit")` remain in `claude_code/installer.py`.
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
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_installer_remote_claude.py -q`
- `pytest tests/knowledge/wiki/test_installer_ledger_hooks.py -q`

---

## Test Specification

See the CREATE block above: `test_default_install_unchanged`, `test_portable_transitions_both_ways`,
`test_reconcile_respects_portable`, `test_portable_install_no_abs_paths`,
`test_foreign_toolkit_entry_untouched`, `test_windows_paths_detected`, `test_remote_portable_sticky`,
`test_cli_portable_flag`; *[rev 0.5]* `test_plain_reinstall_keeps_portable_wikitoolkit_without_toolkits`,
`test_remote_does_not_reset_portable_mode` (D7), `test_windows_wikitoolkit_entry_is_managed` (D6).

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

**Completed by**: sdd-worker (claude-sonnet-5-5)
**Date**: 2026-10-26
**Notes**: Implemented tri-state portable resolution (install_claude_integration resolves once via _current_portable_mode), sticky reconcile_toolkit_entries, portable-aware managed detection, Windows-safe _script_basename (incl. _is_wikitoolkit_entry), --portable/--no-portable CLI flag. New test file 11 passed; all 7 other validation test files pass; ruff clean. Contract anchors verified (line numbers matched).

**Deviations from spec**: none
