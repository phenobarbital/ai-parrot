# TASK-2648: Claude Code installer — managed `.mcp.json` entry reconciliation

**Feature**: FEAT-485 — Expose Toolkits as Local MCP
**Spec**: `sdd/specs/expose-toolkits-as-local-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2645, TASK-2647
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. `parrot claude install` today writes exactly one
hardcoded `wikitoolkit` entry into `.mcp.json`. Generalize to a **managed
entry set**: wikitoolkit (unchanged content) + one `parrot-<name>` entry
per enabled toolkit section, reconciled idempotently, never touching
foreign entries.

---

## Scope

- MODIFY `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py`:
  add `toolkit_mcp_json_entry(root: Path, name: str, section) -> dict`
  returning `{"command": <abs parrot bin>, "args": ["mcp-local", <name>],
  "env": dict(section.env)}`. Resolve the `parrot` binary the same way
  `resolve_wikitoolkit_bin` resolves wikitoolkit (read assets.py for that
  helper and mirror it for the `parrot` script).
- MODIFY `.../claude_code/installer.py`:
  - `_install_mcp_json(root)` → reconciliation: read
    `load_toolkits_config(root)`; managed names =
    `{"wikitoolkit"} ∪ {f"parrot-{n}" for enabled sections}`.
    Add/update managed entries; REMOVE a managed-format `parrot-<n>` entry
    whose section is now disabled/deleted; NEVER modify an entry whose
    content was not written by this machinery (foreign entry with a
    colliding name → warn on stderr + skip). Wikitoolkit entry content
    stays byte-identical to today.
  - `_uninstall_mcp_json(root)` → remove all managed entries; delete the
    file only when it becomes empty (existing behavior at line 321).
  - Managed-entry detection: an entry is "ours" iff its `command` ends with
    the resolved binary name AND `args` matches the managed shape
    (`["mcp"]` for wikitoolkit, `["mcp-local", <name>]` for toolkits).
    Document this rule in a docstring.
- Unit tests (tmp .mcp.json fixtures).

**NOT in scope**: codex installer (TASK-2649); the CLI itself (TASK-2647);
changes to skills/hooks/CLAUDE.md sections of the installer.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` | MODIFY | `toolkit_mcp_json_entry` + parrot-bin resolver |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | MODIFY | reconciliation in `_install_mcp_json`/`_uninstall_mcp_json` |
| `tests/knowledge/wiki/test_installer_toolkit_entries.py` | CREATE | unit tests (corrected path — see Codebase Contract note) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.toolkit_config import load_toolkits_config  # created by TASK-2645
from parrot.knowledge.wiki.claude_code import assets        # existing module
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
def _install_mcp_json(root: Path) -> str:  # line 258
#   .mcp.json lives at PROJECT ROOT, not .claude/ (lines 261-266)
#   current behavior: read/parse .mcp.json, build assets.mcp_json_entry(root)
#   (line 277), compare, write; return status string (lines 283-286)
def _uninstall_mcp_json(root: Path) -> str | None:  # line 293
#   removes wikitoolkit entry; deletes file if empty (line 321)
def install_claude_integration(...):  # line 454 — calls _install_mcp_json (line 492)
#   keep the actions.append(<status string>) reporting convention

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py
def mcp_json_entry(root: Path) -> dict:  # line 95
#   {"command": resolve_wikitoolkit_bin(root), "args": ["mcp"], "env": {}}
def resolve_wikitoolkit_bin(root: Path) -> str  # referenced at assets.py:98 —
#   READ its body before mirroring it for the `parrot` binary

# packages/ai-parrot/src/parrot/mcp/toolkit_config.py (TASK-2645)
class ToolkitSection: enabled: bool; env: dict[str, str]; ...
def load_toolkits_config(root: Path) -> MCPToolkitsConfig
```

### Stale Contract Entry (corrected)
- ~~`tests/wiki/claude_code/test_installer_toolkit_entries.py`~~ — no
  `tests/wiki/` directory exists in this repo. The actual test tree
  mirrors `packages/ai-parrot/src/parrot/knowledge/wiki/` at
  `tests/knowledge/wiki/` (see `tests/knowledge/wiki/test_claude_code.py`,
  which already covers the rest of this installer). Corrected path:
  `tests/knowledge/wiki/test_installer_toolkit_entries.py`.

### Does NOT Exist
- ~~`assets.toolkit_mcp_json_entry`~~ — this task creates it.
- ~~a "managed" marker key inside `.mcp.json` entries~~ — Claude Code
  consumes the file; do NOT add non-schema keys (e.g. `"_managed": true`).
  Managed detection is by command+args shape (documented rule above).
- ~~reconciliation logic in current `_install_mcp_json`~~ — today it
  handles exactly one hardcoded wikitoolkit entry.
- ~~`parrot claude install --toolkits` flag~~ — no new flags; behavior is
  config-driven.

---

## Implementation Notes

### Key Constraints
- Idempotent: running install twice yields identical file content.
- Foreign entries (any name, including a colliding `parrot-<name>` whose
  shape is not ours) are preserved untouched; collision → warn + skip.
- Wikitoolkit entry must remain byte-identical (regression test).
- JSON written with the same formatting conventions the current code uses
  (read `_install_mcp_json` body for indent/sort behavior before writing).
- Status strings follow the existing `".mcp.json — ..."` convention.

---

## Acceptance Criteria

- [ ] Enabled sections → `parrot-<name>` entries with `["mcp-local", name]` args and section `env`
- [ ] Re-run reconciles: disabled/deleted section's managed entry removed
- [ ] Foreign entries untouched; colliding foreign name → warn + skip
- [ ] Wikitoolkit entry byte-identical to pre-feature output
- [ ] Uninstall removes exactly the managed set; file deleted only if empty
- [ ] Tests pass: `pytest tests/wiki/claude_code/test_installer_toolkit_entries.py -v`; ruff clean

---

## Test Specification

```python
# tests/wiki/claude_code/test_installer_toolkit_entries.py
def test_install_writes_toolkit_entries(tmp_root_with_config): ...
def test_install_is_idempotent(tmp_root_with_config): ...
def test_disabled_section_entry_removed_on_rerun(tmp_root_with_config): ...
def test_foreign_entry_untouched(tmp_root_with_config): ...
def test_colliding_foreign_entry_skipped_with_warning(tmp_root_with_config, capsys): ...
def test_wikitoolkit_entry_unchanged(tmp_root_with_config): ...
def test_uninstall_removes_managed_only(tmp_root_with_config): ...
```

---

## Agent Instructions

1. **Read the spec** for full context
2. **Check dependencies** — TASK-2645, TASK-2647 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `_install_mcp_json` and
   `resolve_wikitoolkit_bin` bodies FIRST
4. **Update status** in `sdd/tasks/index/expose-toolkits-as-local-mcp.json` → `"in-progress"`
5. **Implement**, **verify**, **move this file** to `sdd/tasks/completed/`,
   **update index** → `"done"`, **fill in the Completion Note**

---

## Completion Note

**Completed by**: sdd-start (Claude)
**Date**: 2026-09-01
**Notes**:
- `assets.py`: added `resolve_parrot_bin(root)` mirroring
  `resolve_wikitoolkit_bin`'s resolution order (`.venv/bin/parrot` →
  `shutil.which("parrot")` → bare `"parrot"`), and
  `toolkit_mcp_json_entry(root, name, section)` returning
  `{"command": <abs parrot bin>, "args": ["mcp-local", name], "env":
  dict(section.env)}`. `ToolkitSection` is imported only under
  `TYPE_CHECKING` (module already has `from __future__ import
  annotations`) to avoid a new runtime dependency from this leaf module
  onto `parrot.mcp.toolkit_config`.
- `installer.py`: added `_is_managed_toolkit_entry(entry, root, name)` —
  the managed-detection predicate (`command` ends with the resolved
  `parrot` binary name AND `args == ["mcp-local", name]`). Generalized
  `_install_mcp_json` to, after its unchanged wikitoolkit handling,
  `load_toolkits_config(root)` and reconcile one `parrot-<name>` entry per
  *enabled* section: add/update managed entries, remove a managed entry
  whose section is now disabled/deleted, and — for a `parrot-<name>` key
  that exists but does NOT match the managed shape — print a stderr
  warning and skip it untouched (never overwritten). `_uninstall_mcp_json`
  now removes the wikitoolkit entry plus every entry recognized as
  managed by the same predicate, leaving foreign entries (including
  colliding-name foreign `parrot-<name>` entries) in place; the
  single-entry-removed message text (`".mcp.json — wikitoolkit entry
  removed"`) is preserved byte-for-byte when no toolkits were also
  removed, for backward compatibility of the status-string convention.
  Both functions still return early (no file write) when nothing changed,
  preserving idempotency and the exact "already current" message.
- Added `tests/knowledge/wiki/test_installer_toolkit_entries.py` (7
  tests): enabled sections get entries and disabled ones don't; a second
  run with no config change is a no-op byte-for-byte; disabling a
  previously-enabled section removes its entry on re-run; a foreign
  entry with an unrelated name is never touched; a `parrot-<name>` foreign
  entry not matching our shape is left untouched with a stderr warning
  (`capsys`); the wikitoolkit entry stays `== assets.mcp_json_entry(root)`
  after toolkit reconciliation; uninstall removes exactly the managed set
  and leaves a foreign entry in place. All 7 pass; `ruff check` clean on
  all three files touched (verified zero *new* findings on `installer.py`
  via `git stash` diff against the 9 pre-existing findings there).
- Ran the full `tests/knowledge/wiki/` suite (1203 passed, 1 pre-existing
  failure, 7 skipped needing ArangoDB): the one failure
  (`TestInstaller::test_fresh_install_writes_all_artifacts`, an
  `assert len(actions) == 7` off-by-one) reproduces identically via
  `git stash` on the pre-task commit — confirmed pre-existing and
  unrelated to this task, not fixed (out of scope).
- Corrected a stale Codebase Contract entry: the task named
  `tests/wiki/claude_code/test_installer_toolkit_entries.py`, but no
  `tests/wiki/` directory exists in this repo — the real convention
  mirrors `packages/ai-parrot/src/parrot/knowledge/wiki/` at
  `tests/knowledge/wiki/` (where `test_claude_code.py` already covers the
  rest of this installer). Updated the task's Files table and added a
  "Stale Contract Entry (corrected)" note before implementing.

**Deviations from spec**: none, beyond the stale test-path correction
noted above (test location only, not scope/behavior).
