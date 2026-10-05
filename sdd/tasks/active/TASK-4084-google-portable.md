# TASK-4084: Google host: Windows paths, PurePosixPath fix, --portable emission

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4071
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (a)–(e) for **Google Antigravity / Gemini CLI**. This host is the one where
portability matters most: its primary MCP config is **USER-GLOBAL** —
`~/.gemini/config/mcp_config.json` (`default_mcp_config_path()`, google/assets.py:61-63) — and is
shared by every repository on the machine (spec §1 Problem 3, §7 "Gemini config is user-global").
Today `parrot google install` writes into that one file:
- a `wikitoolkit` entry with an absolute `command` AND an absolute `cwd` (google/assets.py:74-80) —
  the last repo installed wins, silently re-pointing every other repo's wiki server;
- `parrot-<name>` toolkit entries with absolute `command`, `--config` and `cwd` (google/assets.py:83-104);
- a `bookstore` entry pinned to `sys.executable` with an absolute `cwd` and a snapshot of
  `PARROT_HOME`/`PARROT_LIBRARY_DIR`… values (google/assets.py:107-127).

Portable emission is what makes the user-global file multi-repo-safe: bare launcher commands, no
`cwd`, relative `--config`, no environment snapshot — the same bytes whichever repo runs the install
(spec §4 `test_portable_config_two_roots`). The repo-local plugin config
`<root>/.agents/plugins/parrot/mcp_config.json` (google/installer.py:250-265) gets the same entries.

Codex S4 / spec §7: managed-entry detection uses `PurePosixPath(...).name` (google/installer.py:72, :94),
which mis-reads `C:\…\Scripts\wikitoolkit.exe`; it must become path-flavour-safe **with** the Windows
branch, not after.

Mode rule (same as Claude TASK-4082 and Codex TASK-4083):
- `--portable` / `--no-portable` land exactly the requested form for **managed** entries; foreign
  entries stay untouched (`_is_managed_*` guards at google/installer.py:234, :189 are kept);
- flag absent → keep the current form. Inference reads the **repo-local plugin file first**
  (it is per-repo, so one repo's choice does not leak into another), then the user-global file;
  nothing found / baked → baked (fresh install byte-identical to today);
- `parrot toolkits` (`mcp/hosts.py::GoogleAdapter.reconcile` → `reconcile_toolkit_entries(root, mcp_path)`,
  hosts.py:219-222) infers the same way — **sticky**. `mcp/hosts.py` is NOT modified.

---

## Scope

- `google/assets.py`: `resolve_binary` via `script_path`; `PORTABLE_TOOLKIT_CONFIG`; keyword-only
  `portable` on `wikitoolkit_mcp_entry`, `toolkit_mcp_entries`, `bookstore_mcp_entry`.
  `default_mcp_config_path` stays unchanged (cited only).
- `google/bookstore.py`: `_is_managed_bookstore_entry` accepts the portable shape;
  `install_bookstore(…, *, portable=False)`. (This file does not emit `sys.executable` itself — it
  calls `assets.bookstore_mcp_entry` — but without these two edits a portable bookstore entry would
  be classified foreign and never updated or uninstalled.)
- `google/installer.py`: `_script_basename` (Windows-safe, replaces `PurePosixPath` at :72 and :94);
  portable-aware `_is_managed_toolkit_entry`; `_current_portable_mode`;
  `reconcile_toolkit_entries(root, mcp_path=None, *, portable: Optional[bool] = None)`;
  `_install_mcp(root, mcp_path=None, *, portable: bool = False)`;
  `install_google_integration(…, portable: Optional[bool] = None)`.
- `google/cli.py`: `--portable/--no-portable` (default unset).
- Write `packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py`.

**NOT in scope**:
- `mcp/hosts.py` (unchanged; `GoogleAdapter.inspect` calls `_is_managed_toolkit_entry(entry, root, name)`,
  which this task makes portable-aware — that is enough).
- Moving Gemini config off the user-global path, or `parrot self doctor`'s collision check (TASK-4080).
- Making `parrot mcp-local` honour `PARROT_PROJECT` (mcp/local_cli.py:183 uses `Path.cwd()`).
- GEMINI.md / skills (no paths).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py` | MODIFY | Windows branch; portable wikitoolkit/toolkit/bookstore entries (no `cwd`, no env snapshot) |
| `packages/ai-parrot/src/parrot/knowledge/wiki/google/bookstore.py` | MODIFY | Portable-aware managed detection; `install_bookstore(portable=)` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py` | MODIFY | Windows-safe basenames (codex S4), tri-state mode, sticky toolkit reconcile |
| `packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py` | MODIFY | `--portable/--no-portable` on `parrot google install` |
| `packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py` | CREATE | Two-roots byte identity, no abs paths, transitions, stickiness, Windows detection |

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
from parrot.knowledge.wiki.google import assets                           # google/installer.py:11
from parrot.knowledge.wiki.google.bookstore import bookstore_status, install_bookstore, uninstall_bookstore  # google/installer.py:12
from parrot.knowledge.wiki.google.installer import (                      # test-side
    _install_mcp, _is_managed_toolkit_entry, _is_managed_wikitoolkit_entry,
    install_google_integration, reconcile_toolkit_entries,
)
from parrot.knowledge.wiki.google.cli import google                       # google/cli.py:37 (click group)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py
PLUGIN_DIR = Path(".agents/plugins/parrot")                               # line 19
def default_mcp_config_path() -> Path:                                    # line 61 — ~/.gemini/config/mcp_config.json (USER-GLOBAL); unchanged
def resolve_binary(root: Path, name: str) -> str:                         # line 66; probe line 68: root / ".venv" / "bin" / name
def wikitoolkit_mcp_entry(root: Path) -> dict[str, Any]:                  # line 74-80 {"command", "args": ["mcp"], "cwd": abs}
def toolkit_mcp_entries(root: Path, sections: dict[str, ToolkitSection]) -> dict[str, dict[str, Any]]:  # line 83-104
#   parrot_bin = resolve_binary(root, "parrot") line 92; config_path = str(root.resolve() / ".parrot" / "mcp-toolkits.yaml") line 93
def bookstore_mcp_entry(root: Path) -> dict[str, Any]:                    # line 107-127; env snapshot 109-118; "command": sys.executable line 121

# packages/ai-parrot/src/parrot/knowledge/wiki/google/bookstore.py
def _is_managed_bookstore_entry(entry: Any) -> bool:                      # line 22; args == [...] line 27
def install_bookstore(root: Path, mcp_path: Optional[Path] = None) -> list[str]:  # line 49; desired_entry = assets.bookstore_mcp_entry(root) line 68
def uninstall_bookstore(root: Path, mcp_path: Optional[Path] = None) -> list[str]:  # line 101 (reuses _is_managed_bookstore_entry)

# packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py
from pathlib import Path, PurePosixPath                                   # line 8
def _load_mcp_config(path: Path) -> dict[str, Any]:                       # line 45 (raises RuntimeError on corrupt JSON)
def _save_mcp_config(path: Path, data: dict[str, Any]) -> None:           # line 63
def _is_managed_wikitoolkit_entry(entry: Any, root: Path) -> bool:        # line 68; PurePosixPath(...) line 72; endswith line 73
def _is_managed_toolkit_entry(entry: Any, root: Path, name: str) -> bool: # line 76; PurePosixPath(...) line 94; endswith 95; is_absolute 102
def toolkit_config_paths(root: Path, mcp_path: Optional[Path] = None) -> tuple[Path, ...]:  # line 142 -> (user-global, <root>/.agents/plugins/parrot/mcp_config.json)
def reconcile_toolkit_entries(root: Path, mcp_path: Optional[Path] = None) -> tuple[list[str], list[str]]:  # line 155
#   enabled_toolkits = … line 169; desired_toolkits = assets.toolkit_mcp_entries(root, enabled_toolkits) line 170
def _install_mcp(root: Path, mcp_path: Optional[Path] = None) -> list[str]:  # line 222
#   wiki_entry = assets.wikitoolkit_mcp_entry(root) line 230; foreign guard line 234;
#   reconcile_toolkit_entries(root, mcp_path) line 247; plugin file wikitoolkit write lines 259-265
def install_google_integration(root, config=None, gitignore=True, bookstore=True, mcp_config_path=None) -> list[str]:  # line 285-291
#   save_project_config line 302; _install_mcp(root, mcp_path=mcp_config_path) line 314; install_bookstore(...) line 325

# packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py
#   "--bookstore/--no-bookstore" line 58; def install( line 63; `    bookstore: bool,` line 67;
#   install_google_integration(root, config, gitignore=gitignore, bookstore=bookstore) line 73

# packages/ai-parrot/src/parrot/mcp/hosts.py:176-225 — GoogleAdapter(mcp_path); reconcile -> reconcile_toolkit_entries(root, self._mcp_path)
```

### Does NOT Exist
- ~~Windows venv handling in `google/`~~ — added via `script_path` only.
- ~~a `portable` parameter / `--portable` flag in `google/`~~ — new.
- ~~Gemini/Antigravity `${VAR}` expansion in `mcp_config.json`~~ — NOT verified; spike S3 (TASK-4069) decides.
- ~~a per-repo Gemini MCP config replacing the user-global file~~ — not in this feature.
- ~~`parrot mcp-local` reading `PARROT_PROJECT`~~ — uses `Path.cwd()` (mcp/local_cli.py:183).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/google/bookstore.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py#default_mcp_config_path",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py#resolve_binary",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py#wikitoolkit_mcp_entry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py#toolkit_mcp_entries",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py#bookstore_mcp_entry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py#PLUGIN_DIR",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/bookstore.py#_is_managed_bookstore_entry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/bookstore.py#install_bookstore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/bookstore.py#uninstall_bookstore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#_load_mcp_config",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#_save_mcp_config",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#_is_managed_wikitoolkit_entry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#_is_managed_toolkit_entry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#toolkit_config_paths",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#reconcile_toolkit_entries",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#_install_mcp",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#install_google_integration",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py#install",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py#google",
    "sym:packages/ai-parrot/src/parrot/mcp/hosts.py#GoogleAdapter.reconcile",
    "sym:packages/ai-parrot/src/parrot/mcp/hosts.py#GoogleAdapter.inspect"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# google/installer.py:234-241 — keep this ordering: foreign first, then "already current",
# else write. Comparing against the REQUESTED entry is what makes the requested mode win.
if existing_wiki is not None and not _is_managed_wikitoolkit_entry(existing_wiki, root):
    actions.append(f"{target_mcp} — wikitoolkit MCP: foreign user configuration preserved")
elif existing_wiki == wiki_entry:
    ...
else:
    servers["wikitoolkit"] = wiki_entry
```

### Key Constraints
- **Portable output is root-independent**: two roots → byte-identical user-global file and plugin
  file (spec §4 `test_portable_config_two_roots`). Hence: no `cwd`, relative `--config`, and **no
  `os.environ` snapshot** in the portable bookstore entry (`PARROT_HOME`/`PARROT_LIBRARY_DIR` values
  are machine paths — the `bookstore` process reads them from its own environment at run time).
- Default output is byte-identical to today on POSIX — the existing
  `tests/knowledge/wiki/test_google_installer_toolkit_entries.py::test_google_entry_pins_config_keeps_cwd`
  must keep passing.
- `_script_basename` deliberately duplicates the private helper TASK-4082 adds to the Claude
  installer (the repo already keeps per-host private copies, e.g. `_upsert_marker_block`) — do not
  import across hosts.
- Inference must never raise: `_load_mcp_config` raises `RuntimeError` on corrupt JSON — catch it
  and treat as "baked".
- Warnings stay on `sys.stderr` as today (google/installer.py:194).

### References in Codebase
- `packages/ai-parrot/src/parrot/mcp/hosts.py:176-225` — GoogleAdapter (user-global primary config).
- `tests/knowledge/wiki/test_google_installer_toolkit_entries.py:18-50` — `mcp_config_path` fixture
  pattern (monkeypatch `assets.default_mcp_config_path`) — tests must NEVER touch the real `~/.gemini`.

---

## Implementation Blueprint

### Steps (in order)
1. `assets.py`: import `script_path`, rewrite the probe, add `PORTABLE_TOOLKIT_CONFIG`, add `portable`
   to the three entry emitters — *why*: spec §3 M5(a)/(b)/(d).
2. `bookstore.py`: portable-aware managed detection + `install_bookstore(portable=)` — *why*: a
   portable entry must remain "ours" to be updated/removed.
3. `installer.py`: `_script_basename` at :72/:94 — *why*: codex S4, before the Windows branch lands.
4. `installer.py`: portable shape in `_is_managed_toolkit_entry`; `_current_portable_mode`; sticky
   `reconcile_toolkit_entries`; thread `portable` through `_install_mcp` and
   `install_google_integration` — *why*: STICKY rule (shared brief) + requested-wins (spec §5).
5. `cli.py`: tri-state flag — *why*: spec §2 New Public Interfaces.
6. Tests — *why*: spec §4 `test_portable_config_two_roots`, `test_portable_entries_no_abs_paths`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from typing import TYPE_CHECKING, Any' packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py)
# AFTER — `from typing import TYPE_CHECKING, Any` (verified: google/assets.py:9)

from parrot.launcher import script_path  # created by TASK-4071 (stdlib-only module)

# occurrences: 1 (verified: grep -c 'PLUGIN_DIR = Path(".agents/plugins/parrot")' packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py)
# AFTER — (verified: google/assets.py:19)
#: Relative toolkit config used by portable toolkit entries (FEAT-633).
PORTABLE_TOOLKIT_CONFIG = ".parrot/mcp-toolkits.yaml"

# occurrences: 1 (verified: grep -c '    venv_binary = root / ".venv" / "bin" / name' packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py)
# REPLACE — (verified: google/assets.py:68)
    venv_binary = script_path(root / ".venv", name)

# occurrences: 1 (verified: grep -c 'def wikitoolkit_mcp_entry(root: Path) -> dict\[str, Any\]:' packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py)
# REPLACE — whole function (verified: google/assets.py:74-80)
def wikitoolkit_mcp_entry(root: Path, *, portable: bool = False) -> dict[str, Any]:
    """Build the wikitoolkit MCP server entry for Antigravity.

    Portable (FEAT-633): ``{"command": "wikitoolkit", "args": ["mcp"]}`` — no absolute ``cwd``,
    so the USER-GLOBAL config holds one entry valid for every repository.
    """
    if portable:
        entry: dict[str, Any] = {"command": "wikitoolkit", "args": ["mcp"]}
        # FILL IN: optional env {"PARROT_PROJECT": "<host variable reference>"} ONLY if spike S3
        # (TASK-4069) shows Antigravity/Gemini expands variables and starts servers outside the
        # workspace root — bounded by spec §5 (no absolute path, env included) and
        # test_portable_config_two_roots (byte-identical across roots).
        return entry
    return {
        "command": resolve_binary(root, "wikitoolkit"),
        "args": ["mcp"],
        "cwd": str(root.resolve()),
    }

# occurrences: 1 (verified: grep -c 'def toolkit_mcp_entries(root: Path, sections: dict\[str, ToolkitSection\]) -> dict\[str, dict\[str, Any\]\]:' packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py)
# REPLACE — signature (:83) and the loop body (:91-104); docstring gains the portable shape
def toolkit_mcp_entries(
    root: Path, sections: dict[str, ToolkitSection], *, portable: bool = False
) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    parrot_bin = "parrot" if portable else resolve_binary(root, "parrot")
    config_path = PORTABLE_TOOLKIT_CONFIG if portable else str(root.resolve() / ".parrot" / "mcp-toolkits.yaml")
    for name in sorted(sections):
        section = sections[name]
        entry: dict[str, Any] = {"command": parrot_bin, "args": ["mcp-local", name, "--config", config_path]}
        if not portable:
            entry["cwd"] = str(root.resolve())
        # FILL IN: portable project pin (same rule as wikitoolkit_mcp_entry) — bounded by spike S3.
        if section.env:
            entry["env"] = dict(section.env)
        entries[f"parrot-{name}"] = entry
    return entries

# occurrences: 1 (verified: grep -c 'def bookstore_mcp_entry(root: Path) -> dict\[str, Any\]:' packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py)
# REPLACE — signature (:107) and insert the portable early return as the first statement
#           (anchor `        "command": sys.executable,` at :121, occurrences 1, stays in the baked branch)
def bookstore_mcp_entry(root: Path, *, portable: bool = False) -> dict[str, Any]:
    """Build bookstore PageIndex MCP server entry for Antigravity.

    Portable (FEAT-633): ``{"command": "bookstore", "args": ["mcp"]}`` — no ``sys.executable``, no
    ``cwd`` and no environment snapshot (its values are machine paths).
    """
    if portable:
        return {"command": "bookstore", "args": ["mcp"]}
    # (existing body, lines 109-127, unchanged)
```
**Why this shape**: baked branches are the verbatim old bodies (dict key order included), so
`json.dumps` output — and therefore the user-global file — is unchanged by default.

### `packages/ai-parrot/src/parrot/knowledge/wiki/google/bookstore.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    return args == \["-m", "parrot.knowledge.bookstore.cli", "mcp"\]' packages/ai-parrot/src/parrot/knowledge/wiki/google/bookstore.py)
# REPLACE — (verified: google/bookstore.py:27)
    if args == ["-m", "parrot.knowledge.bookstore.cli", "mcp"]:
        return True
    # Portable (FEAT-633) managed shape — exact bare command, never a basename match.
    return entry.get("command") == "bookstore" and args == ["mcp"]

# occurrences: 1 (verified: grep -c 'def install_bookstore(root: Path, mcp_path: Optional\[Path\] = None) -> list\[str\]:' packages/ai-parrot/src/parrot/knowledge/wiki/google/bookstore.py)
# REPLACE — signature (:49) and `    desired_entry = assets.bookstore_mcp_entry(root)` (:68, occurrences 1)
def install_bookstore(root: Path, mcp_path: Optional[Path] = None, *, portable: bool = False) -> list[str]:
    desired_entry = assets.bookstore_mcp_entry(root, portable=portable)
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _save_mcp_config(path: Path, data: dict\[str, Any\]) -> None:' packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py)
# AFTER — insert below the end of `_save_mcp_config` (verified: google/installer.py:63-65)


def _script_basename(command: str) -> str:
    """Basename of a command path, separator- and ``.exe``-agnostic (codex S4)."""
    name = command.replace("\\", "/").rsplit("/", 1)[-1]
    return name[:-4] if name.lower().endswith(".exe") else name


def _current_portable_mode(root: Path, mcp_path: Optional[Path] = None) -> bool:
    """Infer the current mode (FEAT-633, sticky) from the managed wikitoolkit entry.

    Reads the repo-local plugin config first (per-repo — one repo's choice must not leak into
    another through the USER-GLOBAL file), then the user-global config. Never raises.
    """
    # FILL IN: for path in (root / assets.PLUGIN_DIR / "mcp_config.json", mcp_path or
    # assets.default_mcp_config_path()): load leniently (catch RuntimeError from _load_mcp_config);
    # on the first file that HAS a "wikitoolkit" entry return
    # entry == assets.wikitoolkit_mcp_entry(root, portable=True); none found -> False.
    # Bounded by "no new state file" (shared brief).
    raise NotImplementedError

# occurrences: 1 (verified: grep -c '    bin_name = PurePosixPath(assets.resolve_binary(root, "wikitoolkit")).name' packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py)
# REPLACE — lines 72-73 (verified: google/installer.py:72; next line
#           `    return isinstance(command, str) and command.endswith(bin_name) and entry.get("args") == ["mcp"]`, occurrences 1)
    return isinstance(command, str) and _script_basename(command) == "wikitoolkit" and entry.get("args") == ["mcp"]

# occurrences: 1 (verified: grep -c '    bin_name = PurePosixPath(assets.resolve_binary(root, "parrot")).name' packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py)
# REPLACE — lines 94-96 (verified: google/installer.py:94; next line
#           `    if not isinstance(command, str) or not command.endswith(bin_name):`, occurrences 1)
    if not isinstance(command, str) or _script_basename(command) != "parrot":
        return False

# occurrences: 1 (verified: grep -c '        if not config_path.is_absolute():' packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py)
# REPLACE — lines 100-103 (context:
#     if len(args) >= 4 and args[2] == "--config":
#         config_path = Path(args[3])
#         if not config_path.is_absolute():
#             return False   — verified google/installer.py:100-103)
    if len(args) >= 4 and args[2] == "--config":
        if args[3] == assets.PORTABLE_TOOLKIT_CONFIG:  # portable form — ours
            return True
        config_path = Path(args[3])
        if not config_path.is_absolute():
            return False
# After both replacements `PurePosixPath` is unused: change line 8 to `from pathlib import Path` (ruff F401).
```

```python
# occurrences: 1 (verified: grep -c 'def reconcile_toolkit_entries(root: Path, mcp_path: Optional\[Path\] = None) -> tuple\[list\[str\], list\[str\]\]:' packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py)
# REPLACE — signature (:155); docstring: "portable: None infers via _current_portable_mode (sticky —
#           the `parrot toolkits` path via mcp/hosts.py::GoogleAdapter.reconcile)."
def reconcile_toolkit_entries(
    root: Path, mcp_path: Optional[Path] = None, *, portable: Optional[bool] = None
) -> tuple[list[str], list[str]]:

# occurrences: 1 (verified: grep -c '    desired_toolkits = assets.toolkit_mcp_entries(root, enabled_toolkits)' packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py)
# REPLACE — (verified: google/installer.py:170)
    if portable is None:
        portable = _current_portable_mode(root, mcp_path)
    desired_toolkits = assets.toolkit_mcp_entries(root, enabled_toolkits, portable=portable)

# occurrences: 1 (verified: grep -c 'def _install_mcp(root: Path, mcp_path: Optional\[Path\] = None) -> list\[str\]:' packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py)
# REPLACE — signature (:222), `    wiki_entry = assets.wikitoolkit_mcp_entry(root)` (:230, occurrences 1) and
#           `    toolkit_actions, _toolkit_warnings = reconcile_toolkit_entries(root, mcp_path)` (:247, occurrences 1)
def _install_mcp(root: Path, mcp_path: Optional[Path] = None, *, portable: bool = False) -> list[str]:
    wiki_entry = assets.wikitoolkit_mcp_entry(root, portable=portable)
    toolkit_actions, _toolkit_warnings = reconcile_toolkit_entries(root, mcp_path, portable=portable)
# The plugin-file write (`    if plugin_servers.get("wikitoolkit") != wiki_entry:`, :262, occurrences 1)
# needs no change — it already writes whatever wiki_entry is.

# occurrences: 1 (verified: grep -c '    bookstore: bool = True,' packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py)
# REPLACE — install_google_integration signature tail (verified: google/installer.py:289-291); the
#           single-line anchor `    mcp_config_path: Optional[Path] = None,` has 3 occurrences (:290, :332, :407),
#           so use this 3-line context:
#     bookstore: bool = True,
#     mcp_config_path: Optional[Path] = None,
# ) -> list[str]:
    bookstore: bool = True,
    mcp_config_path: Optional[Path] = None,
    portable: Optional[bool] = None,
) -> list[str]:
# Docstring Args: portable — True: bare launcher commands, no cwd (multi-repo-safe user-global config);
#   False: baked absolute paths (today); None: keep the current form (plugin file, then user-global).

# occurrences: 1 (verified: grep -c '    save_project_config(root, config)' packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py)
# AFTER — (verified: google/installer.py:302)
    if portable is None:
        portable = _current_portable_mode(root, mcp_config_path)

# REPLACE — call sites (each occurrences 1, verified :314 and :325)
    actions.extend(_install_mcp(root, mcp_path=mcp_config_path, portable=portable))
        actions.extend(install_bookstore(root, mcp_path=mcp_config_path, portable=portable))
```
**Why**: `_install_mcp` passes the resolved mode explicitly; only the shared toolkits path
(`reconcile_toolkit_entries` without a mode) infers — that is the sticky rule.

### `packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "--bookstore/--no-bookstore",' packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py)
# AFTER — insert a new decorator after the option block starting at `    "--bookstore/--no-bookstore",`
#         (verified: google/cli.py:57-62), i.e. directly above `def install(` (:63)
@click.option(
    "--portable/--no-portable",
    default=None,
    help="Emit bare launcher commands with no absolute paths or cwd — required for a multi-repo-safe "
    "~/.gemini/config/mcp_config.json. Default: keep the current form (baked on a fresh install).",
)

# occurrences: 1 (verified: grep -c '    bookstore: bool,' packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py)
# AFTER — (verified: google/cli.py:67)
    portable: Optional[bool],

# occurrences: 1 (verified: grep -c '        actions = install_google_integration(root, config, gitignore=gitignore, bookstore=bookstore)' packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py)
# REPLACE — (verified: google/cli.py:73)
        actions = install_google_integration(
            root, config, gitignore=gitignore, bookstore=bookstore, portable=portable
        )
```

### `packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py` (CREATE)
```python
"""FEAT-633 TASK-4084 — Google/Gemini: portable emission for the USER-GLOBAL config."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Iterator

import pytest
from parrot.knowledge.wiki.google import assets
from parrot.knowledge.wiki.google.bookstore import _is_managed_bookstore_entry
from parrot.knowledge.wiki.google.installer import (
    _is_managed_toolkit_entry,
    _is_managed_wikitoolkit_entry,
    install_google_integration,
    reconcile_toolkit_entries,
)

_TOOLKITS = "toolkits:\n  stub:\n    class: tests.mcp.stub_toolkit.StubToolkit\n"


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _make_root(path: Path) -> Path:
    (path / ".parrot").mkdir(parents=True)
    (path / ".parrot" / "mcp-toolkits.yaml").write_text(_TOOLKITS)
    venv_bin = path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    for name in ("wikitoolkit", "parrot"):
        (venv_bin / name).write_text("")
    return path


def _install(root: Path, cfg: Path, portable: bool | None) -> None:
    install_google_integration(root, gitignore=False, bookstore=False, mcp_config_path=cfg, portable=portable)


@pytest.fixture
def global_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = tmp_path / "gemini" / "mcp_config.json"
    monkeypatch.setattr(assets, "default_mcp_config_path", lambda: cfg)  # never touch the real ~/.gemini
    return cfg


def test_portable_config_two_roots(tmp_path: Path, global_cfg: Path) -> None:
    """Spec §4: --portable output from two different roots is byte-identical (committable / shareable)."""
    cfg_a, cfg_b = tmp_path / "a.json", tmp_path / "b.json"
    root_a, root_b = _make_root(tmp_path / "repo-a"), _make_root(tmp_path / "repo-b")
    _install(root_a, cfg_a, True)
    _install(root_b, cfg_b, True)
    assert cfg_a.read_bytes() == cfg_b.read_bytes()
    plugin = Path(assets.PLUGIN_DIR) / "mcp_config.json"
    assert (root_a / plugin).read_bytes() == (root_b / plugin).read_bytes()


def test_portable_entries_no_abs_paths(tmp_path: Path, global_cfg: Path) -> None:
    root = _make_root(tmp_path / "repo")
    _install(root, global_cfg, True)
    servers = json.loads(global_cfg.read_text())["mcpServers"]
    assert all("cwd" not in entry for entry in servers.values())
    for text in _strings(servers):
        assert not os.path.isabs(text) and str(root) not in text, text
    bookstore_entry = assets.bookstore_mcp_entry(root, portable=True)
    assert bookstore_entry == {"command": "bookstore", "args": ["mcp"]} and sys.executable not in str(bookstore_entry)


def test_default_emission_unchanged(tmp_path: Path, global_cfg: Path) -> None:
    root = _make_root(tmp_path / "repo")
    _install(root, global_cfg, None)
    servers = json.loads(global_cfg.read_text())["mcpServers"]
    assert servers["wikitoolkit"] == {
        "command": str(root / ".venv" / "bin" / "wikitoolkit"),
        "args": ["mcp"],
        "cwd": str(root.resolve()),
    }
    assert servers["parrot-stub"]["cwd"] == str(root.resolve())


def test_portable_transitions_and_sticky_reconcile(tmp_path: Path, global_cfg: Path) -> None:
    root = _make_root(tmp_path / "repo")
    _install(root, global_cfg, True)
    _install(root, global_cfg, False)
    assert "cwd" in json.loads(global_cfg.read_text())["mcpServers"]["wikitoolkit"]
    _install(root, global_cfg, True)
    _install(root, global_cfg, None)  # flag absent keeps portable
    assert json.loads(global_cfg.read_text())["mcpServers"]["wikitoolkit"] == {"command": "wikitoolkit", "args": ["mcp"]}
    # FILL IN: add a second toolkit to .parrot/mcp-toolkits.yaml, call reconcile_toolkit_entries(root, global_cfg)
    # (the mcp/hosts.py::GoogleAdapter path) and assert the new entry has args[-1] == assets.PORTABLE_TOOLKIT_CONFIG
    # and no "cwd" — bounded by the STICKY rule.
    raise NotImplementedError


def test_foreign_entries_untouched(tmp_path: Path, global_cfg: Path) -> None:
    root = _make_root(tmp_path / "repo")
    foreign = {"command": "node", "args": ["wiki.js"]}
    global_cfg.parent.mkdir(parents=True, exist_ok=True)
    global_cfg.write_text(json.dumps({"mcpServers": {"wikitoolkit": foreign, "parrot-stub": foreign}}))
    for mode in (True, False):
        _install(root, global_cfg, mode)
        servers = json.loads(global_cfg.read_text())["mcpServers"]
        assert servers["wikitoolkit"] == foreign and servers["parrot-stub"] == foreign


def test_windows_paths_detected(tmp_path: Path) -> None:
    """codex S4: PurePosixPath no longer mis-reads Windows script paths."""
    assert _is_managed_wikitoolkit_entry({"command": "C:\\r\\.venv\\Scripts\\wikitoolkit.exe", "args": ["mcp"]}, tmp_path)
    assert _is_managed_toolkit_entry({"command": "C:\\r\\.venv\\Scripts\\parrot.exe", "args": ["mcp-local", "x"]}, tmp_path, "x")
    assert _is_managed_toolkit_entry(
        {"command": "parrot", "args": ["mcp-local", "x", "--config", assets.PORTABLE_TOOLKIT_CONFIG]}, tmp_path, "x"
    )
    assert _is_managed_bookstore_entry({"command": "bookstore", "args": ["mcp"]})
```

### FILL IN checklist
- [ ] `assets.py::wikitoolkit_mcp_entry` / `toolkit_mcp_entries` portable project pin — bounded by spike S3 (TASK-4069) + byte-identity across roots.
- [ ] `installer.py::_current_portable_mode` — plugin file first, then user-global; never raises; no state file.
- [ ] `test_portable_transitions_and_sticky_reconcile` — the reconcile half; bounded by the STICKY rule.

---

## Acceptance Criteria

- [ ] `resolve_binary` uses `script_path(root / ".venv", name)`; no `".venv" / "bin"` literal and no `PurePosixPath` remain under `google/`.
- [ ] `parrot google install --portable` writes wikitoolkit, toolkit and bookstore entries with no absolute path in `command`, `args`, `cwd` or `env`, and no `sys.executable` (spec §5).
- [ ] Two roots produce byte-identical portable user-global and plugin configs (spec §4 `test_portable_config_two_roots`).
- [ ] Without `--portable` a fresh install is byte-identical to today; `--portable`/`--no-portable` land exactly the requested form for managed entries; foreign `wikitoolkit`/`parrot-<name>`/`bookstore` entries are never touched.
- [ ] `reconcile_toolkit_entries(root, mcp_path)` (the `parrot toolkits` path) follows the current wikitoolkit form; `mcp/hosts.py` unchanged.
- [ ] Windows `Scripts\<name>.exe` commands are recognised as managed (codex S4).
- [ ] Existing Google suites pass; `ruff check` clean on the four modified files.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_google_installer_conventions.py -q`
- `pytest tests/knowledge/wiki/test_google_installer_toolkit_entries.py -q`
- `pytest tests/knowledge/wiki/test_google_integration.py -q`
- `pytest tests/knowledge/wiki/test_google_bookstore.py -q`

---

## Test Specification

See the CREATE block above: `test_portable_config_two_roots`, `test_portable_entries_no_abs_paths`,
`test_default_emission_unchanged`, `test_portable_transitions_and_sticky_reconcile`,
`test_foreign_entries_untouched`, `test_windows_paths_detected`.

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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4084 parrot-installer verified`
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
