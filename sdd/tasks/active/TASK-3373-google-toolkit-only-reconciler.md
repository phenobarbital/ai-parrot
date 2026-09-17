# TASK-3373: Google Antigravity toolkit-only reconciler (dual config)

**Feature**: FEAT-570 — `parrot toolkits` on-demand local-MCP toolkit installation
**Spec**: `sdd/specs/expose-local-mcp-tools.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (Google half), driven by design research **S1** (CONFIRM) and
**S8** (ESCALATE → spec §8 Q1).

`google/installer.py::_install_mcp` (`:139`) writes the wikitoolkit entry
(`:148-160`), then the toolkit entries (`:162-186`), then cleans up disabled ones
(`:187-191`), and *also* maintains a second file — the repo-local workspace plugin
config at `.agents/plugins/parrot/mcp_config.json` (`:214`). `parrot toolkits`
must reconcile only the toolkit entries, in **both** files, and never touch
wikitoolkit (AC5).

Google is the host that breaks the "all detected hosts" symmetry: its primary
config is **user-global** — `~/.gemini/config/mcp_config.json`
(`google/assets.py:59-61`) — shared by every project on the machine, unlike
Claude's repo `.mcp.json` and Codex's repo `.codex/config.toml`. Spec §8 Q1 is
still open on the targeting policy; this task implements the spec's declared
**interim default (a)**: reconcile it when it exists, and make the user-global
scope reportable so the CLI can warn.

---

## Scope

- Extract the toolkit-entry reconciliation out of `_install_mcp` into a public
  `reconcile_toolkit_entries(root, mcp_path=None)` covering **both** config files.
- Refactor `_install_mcp` to call it.
- Expose the two config paths so TASK-3374's adapter can report scope.
- Test wikitoolkit preservation, foreign-entry preservation, and that the
  user-global path is never hardcoded in tests (always monkeypatched).

**NOT in scope**: the `HostAdapter` protocol and `detect_hosts` warning
(TASK-3374), removing `--toolkits` from `google/cli.py` (TASK-3379), resolving
spec §8 Q1 (owner decision).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py` | MODIFY | Extract `reconcile_toolkit_entries`, expose config paths |
| `tests/knowledge/wiki/test_google_installer_toolkit_entries.py` | MODIFY | Wikitoolkit + foreign + dual-file coverage |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.toolkit_config import load_toolkits_config   # verified: toolkit_config.py:105
from parrot.knowledge.wiki.google import assets              # verified: google/assets.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py
def _load_mcp_config(path: Path) -> dict[str, Any]: ...        # line 45
def _save_mcp_config(path: Path, data: dict[str, Any]) -> None: ...  # line 60
def _is_managed_wikitoolkit_entry(entry: Any, root: Path) -> bool: ...  # line 65
def _is_managed_toolkit_entry(entry: Any, root: Path, name: str) -> bool: ...  # line 73
    # mirrors claude_code/installer.py::_is_managed_toolkit_entry (see its docstring at :84)
def _install_mcp(root: Path, mcp_path: Optional[Path] = None) -> list[str]:   # line 139
    # line 141: `from parrot.mcp.toolkit_config import load_toolkits_config`  (local import)
    # line 144: `target_mcp = mcp_path or assets.default_mcp_config_path()`
    # line 145: `mcp_data = _load_mcp_config(target_mcp)`
    # line 146: `servers = mcp_data.setdefault("mcpServers", {})`
    # line 149: `wiki_entry = assets.wikitoolkit_mcp_entry(root)`     <- NOT ours to touch
    # line 153: foreign wikitoolkit preserved; :156 already current; :158 installed
    # line 163: `cfg = load_toolkits_config(root)`
    # line 164: `enabled_toolkits = {n: s for n, s in cfg.toolkits.items() if s.enabled}`
    # line 165: `desired_toolkits = assets.toolkit_mcp_entries(root, enabled_toolkits)`
    # line 171-186: upsert loop; :176 foreign skip via _is_managed_toolkit_entry
    # line 187-191: cleanup — `if name != "wikitoolkit" and name.startswith("parrot-")`
    #               and `raw_name not in enabled_toolkits and _is_managed_toolkit_entry(...)`
    # line 205: comment "Also maintain workspace plugin (.agents/plugins/parrot)"
    # line 214: `plugin_mcp_file = plugin_dir / "mcp_config.json"`
    # line 216-219: writes `{"mcpServers": plugin_servers}` when changed
def install_google_integration(...) -> list[str]: ...          # line 239
def uninstall_google_integration(...) -> list[str]: ...        # line 304
    # line 363-366: removes the plugin mcp_config.json

# packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py
PLUGIN_DIR = Path(".agents/plugins/parrot")                    # line 19
def default_mcp_config_path() -> Path: ...                     # line 59
    # returns Path.home() / ".gemini" / "config" / "mcp_config.json"   <- USER-GLOBAL
def resolve_binary(root: Path, name: str) -> str: ...          # line 64
def wikitoolkit_mcp_entry(root: Path) -> dict[str, Any]: ...   # line 72
def toolkit_mcp_entries(root: Path, sections: dict[str, ToolkitSection]) -> dict[str, dict[str, Any]]:  # line 81
    # line 95: `"args": ["mcp-local", name, "--config", config_path]`
    # line 99: `entry["env"] = dict(section.env)`   <- env copied VERBATIM
def plugin_manifest() -> dict[str, Any]: ...                   # line 129
```

### Does NOT Exist
- ~~a repo-relative Google MCP config~~ — `default_mcp_config_path()` is
  `~/.gemini/config/mcp_config.json`, **user-global**. Never hardcode a real home
  path in a test; always pass `mcp_path=` or monkeypatch.
- ~~`google.installer.reconcile_toolkit_entries`~~ — what THIS task creates.
- ~~`assets.plugin_mcp_config_path()`~~ — there is no such helper; the plugin file
  is built inline as `root / assets.PLUGIN_DIR / "mcp_config.json"`
  (verified: `installer.py:214`).
- ~~`ToolkitSection.env` interpolation~~ — values are copied verbatim (`assets.py:99`).
- ~~`codex`-style marker blocks~~ — Google's config is JSON, reconciled per key.
- ~~`_install_mcp_json`~~ / ~~`reconcile_toolkit_tables`~~ — those are the Claude and
  Codex function names respectively.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_google_installer_toolkit_entries.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#_install_mcp",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#_is_managed_toolkit_entry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#_load_mcp_config",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#_save_mcp_config",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py#toolkit_mcp_entries",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py#default_mcp_config_path",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#load_toolkits_config"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Two files, one operation.** Both the user-global `mcp_config.json` and the
  repo plugin `mcp_config.json` carry toolkit entries and must stay consistent.
- Never read or write the `"wikitoolkit"` key in the new function (AC5).
- The existing cleanup guard already excludes `"wikitoolkit"` (`:189`) — preserve
  that exact condition when lifting the loop.
- Behavior-preserving: `_install_mcp`'s returned action list must not change.
- Tests must never touch a real `~/.gemini` — always pass `mcp_path=tmp_path/...`.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py:162-219` — the
  code being split
- `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py:462` — the
  sibling Claude extraction (TASK-3371), for shape consistency

---

## Implementation Blueprint

### Steps (in order)
1. Add `toolkit_config_paths(root, mcp_path=None)` returning both paths — *why*:
   TASK-3374's adapter must report Google's dual, partly user-global scope, and
   the CLI needs it to warn (spec §8 Q1 interim default (a)).
2. Add `reconcile_toolkit_entries(root, mcp_path=None)` reconciling toolkit keys in
   both files — *why*: one operation, so the two files cannot drift.
3. Refactor `_install_mcp` to keep its wikitoolkit work and delegate the rest —
   *why*: one implementation; a copy-paste would drift.
4. Extend the tests — *why*: AC5 plus the dual-file behavior is not observable
   from the refactor alone.

### `packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'def _install_mcp(root: Path, mcp_path: Optional[Path] = None) -> list[str]:' packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py)
# BEFORE — insert above `def _install_mcp(root: Path, mcp_path: Optional[Path] = None) -> list[str]:`
# (verified: google/installer.py:139)
def toolkit_config_paths(root: Path, mcp_path: Optional[Path] = None) -> tuple[Path, ...]:
    """Return the two files that carry Antigravity toolkit entries, primary first.

    (1) the USER-GLOBAL config — `~/.gemini/config/mcp_config.json`
        (verified: google/assets.py:59) — shared by every project on the machine,
        which is why `parrot toolkits` warns before writing it (spec §8 Q1);
    (2) the repo-local workspace plugin config
        `<root>/.agents/plugins/parrot/mcp_config.json` (verified: installer.py:214).
    """
    primary = mcp_path or assets.default_mcp_config_path()
    return (primary, root / assets.PLUGIN_DIR / "mcp_config.json")


def reconcile_toolkit_entries(
    root: Path, mcp_path: Optional[Path] = None
) -> tuple[list[str], list[str]]:
    """Reconcile ONLY `parrot-<name>` entries, in BOTH Antigravity config files.

    Never reads or writes the "wikitoolkit" key in either file (FEAT-570 AC5).
    Upserts one entry per ENABLED section, preserves a `parrot-<name>` key whose
    content is not our shape (reported as a warning), and deletes managed entries
    whose section is disabled or gone.

    Returns:
        (actions, warnings) — human-readable strings.
    """
    # FILL IN: lift the toolkit half of _install_mcp (verified: google/installer.py:162-191)
    # — `load_toolkits_config` -> enabled sections -> `assets.toolkit_mcp_entries(...)`
    # -> upsert with the `_is_managed_toolkit_entry` foreign check at :176 -> the
    # cleanup loop at :187-191 (keep its `name != "wikitoolkit"` guard verbatim) —
    # and apply the SAME reconciliation to the plugin file from
    # `toolkit_config_paths(...)[1]`, writing each file only when its content changed
    # (pattern verified: installer.py:217). Bounded by AC5.
    raise NotImplementedError
```
**Why this shape**: `toolkit_config_paths` is public because the adapter in
TASK-3374 needs both paths *and* the knowledge that index 0 may be user-global —
that is what lets `parrot toolkits` print the "this affects all projects" warning
the spec's interim default (a) requires. Keeping `mcp_path` as the first override
preserves the existing test seam so no test ever writes a real `~/.gemini`. The
`(actions, warnings)` return matches the Claude and Codex siblings.

```python
# occurrences: 1 (verified: grep -cF 'def _install_mcp(root: Path, mcp_path: Optional[Path] = None) -> list[str]:' packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py)
# MODIFY `_install_mcp` (verified: google/installer.py:139): keep the wikitoolkit
# upsert at :148-160 and the plugin manifest/skill work, then DELETE :162-191 and
# call `reconcile_toolkit_entries(root, mcp_path)` in their place, extending its
# `actions` list with what the call returns.
# FILL IN: the delegation + action-list assembly — the returned list's content must
# be unchanged for existing callers; bounded by the existing
# test_google_installer_toolkit_entries.py assertions.
```
**Why**: `_install_mcp` legitimately owns wikitoolkit; only the toolkit half moves.

### `tests/knowledge/wiki/test_google_installer_toolkit_entries.py` (MODIFY)
```python
# ADD (keep existing cases — they are the refactor's regression net):
def test_reconcile_preserves_wikitoolkit_entry(tmp_path): ...
def test_reconcile_preserves_foreign_toolkit_entry(tmp_path): ...
def test_reconcile_updates_both_config_files(tmp_path): ...
def test_toolkit_config_paths_reports_user_global_first(tmp_path): ...
# FILL IN: bodies — EVERY case must pass `mcp_path=tmp_path / "mcp_config.json"`;
# none may rely on the real home directory. The wikitoolkit case compares the
# entry's exact dict value before and after. Bounded by AC5.
```
**Why**: a test that forgets `mcp_path=` would write into the developer's real
`~/.gemini/config/mcp_config.json` — a genuinely destructive test failure mode,
and the reason the seam exists.

### FILL IN checklist
- [ ] `installer.py::reconcile_toolkit_entries` — lift the toolkit half, apply to both files; bounded by AC5
- [ ] `installer.py::_install_mcp` — delegate, preserve its returned action list; bounded by existing tests
- [ ] `test_google_installer_toolkit_entries.py` — four cases, all passing `mcp_path=`; bounded by AC5

---

## Acceptance Criteria

- [ ] `reconcile_toolkit_entries` is importable from
      `parrot.knowledge.wiki.google.installer` and returns `(actions, warnings)`
- [ ] `toolkit_config_paths(root)` returns exactly two paths, user-global first
- [ ] A toolkit-only reconcile leaves the `wikitoolkit` entry **byte-identical** in
      both files
- [ ] A foreign `parrot-<name>` entry is preserved and reported as a warning
- [ ] A disabled/removed section's managed entry is deleted from both files
- [ ] `_install_mcp`'s returned action list is unchanged
- [ ] No test writes outside `tmp_path` (no real `~/.gemini` access)
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py`

---

## Validation Commands

- `pytest tests/knowledge/wiki/test_google_installer_toolkit_entries.py -q`
- `pytest tests/knowledge/wiki/test_google_integration.py -q`
- `pytest tests/knowledge/wiki/test_google_bookstore.py -q`

---

## Test Specification

```python
# tests/knowledge/wiki/test_google_installer_toolkit_entries.py
from parrot.knowledge.wiki.google.installer import (
    reconcile_toolkit_entries, toolkit_config_paths,
)


def test_toolkit_config_paths_reports_user_global_first(tmp_path):
    paths = toolkit_config_paths(tmp_path, mcp_path=tmp_path / "mcp_config.json")
    assert paths[0] == tmp_path / "mcp_config.json"
    assert paths[1] == tmp_path / ".agents" / "plugins" / "parrot" / "mcp_config.json"


def test_reconcile_preserves_wikitoolkit_entry(tmp_path):
    """AC5 — the wiki server is not ours to touch, in either file."""
    # FILL IN: seed both files with a wikitoolkit entry, snapshot them, reconcile
    # with mcp_path=..., assert deep equality of the wikitoolkit values
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 Module 2, §8 Q1, design research S1 and S8).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — confirm `_install_mcp` is still at `:139`,
   the plugin file write at `:214`, and `default_mcp_config_path` at `assets.py:59`.
4. **Update status** in `sdd/tasks/index/expose-local-mcp-tools.json` → `"in-progress"`.
5. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`.
6. **Verify** all acceptance criteria — especially that no test touches real `$HOME`.
7. **Move this file** to `sdd/tasks/completed/TASK-3373-google-toolkit-only-reconciler.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
