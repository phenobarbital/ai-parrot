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
| `tests/wiki/claude_code/test_installer_toolkit_entries.py` | CREATE | unit tests |

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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
