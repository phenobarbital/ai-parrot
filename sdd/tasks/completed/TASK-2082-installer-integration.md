# TASK-2082: Add .mcp.json installer integration

**Feature**: FEAT-403 — MCP Local Server Core + WikiToolkit MCP
**Spec**: `sdd/specs/mcp-local-server-wikitoolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2081
**Assigned-to**: unassigned

---

## Context

`parrot claude install` currently wires up the PreToolUse nudge hook,
CLAUDE.md section, permissions, and git hook. This task adds a new step
that writes the `.mcp.json` file so Claude Code starts the wikitoolkit
MCP server automatically. Uninstall removes the entry.

Implements spec Module 7.

---

## Scope

- Add `_install_mcp_json(root)` step to `installer.py`
- Add `_uninstall_mcp_json(root)` to the uninstall function
- Add `.mcp.json` status to `integration_status()`
- Update `assets.py` with MCP-related constants
- Update the managed CLAUDE.md section to mention MCP tools
- Write unit tests

**NOT in scope**: MCP server code (TASK-2081). Core MCP infrastructure (TASK-2076-2078).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | MODIFY | Add _install_mcp_json, _uninstall_mcp_json, update integration_status |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` | MODIFY | Add MCP_JSON_ENTRY constant, update CLAUDE_MD_SECTION |
| `packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py` | CREATE | Unit tests for MCP json install/uninstall |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Installer (verified: installer.py)
from parrot.knowledge.wiki.claude_code import assets  # line 31
from parrot.knowledge.wiki.project import (
    WikiConfigError, WikiProjectConfig, config_path,
    load_project_config, save_project_config,
)  # lines 32-37

# Helper functions in installer.py
def _upsert_marker_block(text, block, begin, end) -> str  # line 48
def _remove_marker_block(text, begin, end) -> str  # line 71
def _load_settings(path) -> Optional[dict]  # line 131
def _write_settings(path, settings) -> None  # line 157
```

### Existing Installer Structure
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
def install_claude_integration(root, config=None, git_hook=True, gitignore=True) -> list[str]:  # line 385
    # Steps: config → claude_md → settings_hook → permissions → slash_command → git_hook → gitignore
    # Add _install_mcp_json between permissions and slash_command

def uninstall_claude_integration(root) -> list[str]:  # line 434
    # Steps: claude_md → settings.json → settings.local.json → slash_command → git_hook
    # Add _uninstall_mcp_json

def integration_status(root) -> dict[str, Any]:  # line 560
    # Returns dict of artifact → bool
    # Add "mcp_json" key
```

### Existing Assets Constants
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py
HOOK_COMMAND = "..."  # line 21
HOOK_MATCHER = "..."  # line 27
CLAUDE_MD_SECTION = "..."  # line 50
CLAUDE_MD_BEGIN = "<!-- parrot:wiki:begin -->"
CLAUDE_MD_END = "<!-- parrot:wiki:end -->"
PERMISSION_RULES = [...]  # list of Bash permission patterns
SLASH_COMMAND_FILENAME = "parrotwiki.md"
SLASH_COMMAND_MD = "..."
```

### .mcp.json Format (Claude Code standard)
```json
{
  "mcpServers": {
    "wikitoolkit": {
      "command": "wikitoolkit",
      "args": ["mcp"],
      "env": {}
    }
  }
}
```

### Does NOT Exist
- ~~`_install_mcp_json`~~ — does not exist yet; this task creates it
- ~~`_uninstall_mcp_json`~~ — does not exist yet; this task creates it
- ~~`.mcp.json` handling in installer~~ — not currently present

---

## Implementation Notes

### _install_mcp_json Pattern
```python
def _install_mcp_json(root: Path) -> str:
    path = root / ".mcp.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    else:
        data = {}

    servers = data.setdefault("mcpServers", {})
    if "wikitoolkit" in servers:
        # Check if entry matches current config
        expected = assets.MCP_JSON_ENTRY
        if servers["wikitoolkit"] == expected:
            return ".mcp.json — wikitoolkit entry already current"
        servers["wikitoolkit"] = expected
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return ".mcp.json — wikitoolkit entry updated"

    servers["wikitoolkit"] = assets.MCP_JSON_ENTRY
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return ".mcp.json — wikitoolkit entry added"
```

### _uninstall_mcp_json Pattern
```python
def _uninstall_mcp_json(root: Path) -> str:
    path = root / ".mcp.json"
    if not path.exists():
        return ".mcp.json — not present"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ".mcp.json — could not parse, skipping"

    servers = data.get("mcpServers", {})
    if "wikitoolkit" not in servers:
        return ".mcp.json — no wikitoolkit entry"

    del servers["wikitoolkit"]
    if not servers:
        data.pop("mcpServers", None)
    if not data:
        path.unlink()
        return ".mcp.json — removed (was empty)"
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return ".mcp.json — wikitoolkit entry removed"
```

### Key Constraints
- Preserve other MCP server entries in `.mcp.json` (don't overwrite the whole file)
- `.mcp.json` is project-root level, NOT inside `.claude/`
- The uninstall should remove the file entirely if it becomes empty

---

## Acceptance Criteria

- [ ] `parrot claude install` writes `.mcp.json` with wikitoolkit entry
- [ ] `parrot claude install` is idempotent (re-run doesn't duplicate)
- [ ] `parrot claude uninstall` removes the wikitoolkit entry
- [ ] Other MCP server entries in `.mcp.json` are preserved
- [ ] `integration_status()` reports `"mcp_json": True/False`
- [ ] Tests pass: `pytest packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py
import pytest
import json
from pathlib import Path
from parrot.knowledge.wiki.claude_code.installer import (
    install_claude_integration,
    uninstall_claude_integration,
    integration_status,
)


@pytest.fixture
def repo_root(tmp_path):
    """Minimal repo structure for installer tests."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".parrot").mkdir()
    return tmp_path


class TestMCPJsonInstall:
    def test_install_creates_mcp_json(self, repo_root):
        install_claude_integration(repo_root)
        mcp_json = repo_root / ".mcp.json"
        assert mcp_json.exists()
        data = json.loads(mcp_json.read_text())
        assert "wikitoolkit" in data["mcpServers"]
        assert data["mcpServers"]["wikitoolkit"]["command"] == "wikitoolkit"

    def test_install_idempotent(self, repo_root):
        install_claude_integration(repo_root)
        install_claude_integration(repo_root)
        data = json.loads((repo_root / ".mcp.json").read_text())
        assert len(data["mcpServers"]) == 1

    def test_install_preserves_other_servers(self, repo_root):
        mcp_json = repo_root / ".mcp.json"
        mcp_json.write_text(json.dumps({
            "mcpServers": {"other-server": {"command": "other"}}
        }))
        install_claude_integration(repo_root)
        data = json.loads(mcp_json.read_text())
        assert "other-server" in data["mcpServers"]
        assert "wikitoolkit" in data["mcpServers"]


class TestMCPJsonUninstall:
    def test_uninstall_removes_entry(self, repo_root):
        install_claude_integration(repo_root)
        uninstall_claude_integration(repo_root)
        mcp_json = repo_root / ".mcp.json"
        if mcp_json.exists():
            data = json.loads(mcp_json.read_text())
            assert "wikitoolkit" not in data.get("mcpServers", {})

    def test_uninstall_preserves_other_servers(self, repo_root):
        mcp_json = repo_root / ".mcp.json"
        mcp_json.write_text(json.dumps({
            "mcpServers": {
                "other-server": {"command": "other"},
                "wikitoolkit": {"command": "wikitoolkit", "args": ["mcp"]}
            }
        }))
        uninstall_claude_integration(repo_root)
        data = json.loads(mcp_json.read_text())
        assert "other-server" in data["mcpServers"]
        assert "wikitoolkit" not in data["mcpServers"]


class TestIntegrationStatus:
    def test_status_reports_mcp_json(self, repo_root):
        status = integration_status(repo_root)
        assert "mcp_json" in status
        assert status["mcp_json"] is False
        install_claude_integration(repo_root)
        status = integration_status(repo_root)
        assert status["mcp_json"] is True
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-2081 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `installer.py` and `assets.py` for current structure
4. **Update status** in `sdd/tasks/index/mcp-local-server-wikitoolkit.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2082-installer-integration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-03
**Notes**: Added `MCP_JSON_ENTRY` constant to `assets.py` and a short
paragraph to `CLAUDE_MD_SECTION` pointing agents at the native
`wiki_query`/`wiki_page`/etc. MCP tools when present. Added
`_install_mcp_json()`/`_uninstall_mcp_json()` to `installer.py`, wired
`_install_mcp_json` between `_install_permissions` and
`_install_slash_command` in `install_claude_integration` (per the task's
Existing Installer Structure note), and `_uninstall_mcp_json` before the
slash-command removal in `uninstall_claude_integration`. Added an
`"mcp_json"` key to `integration_status()`. All 9 unit tests pass
(6 from the task's Test Specification + 3 extra: stale-entry update,
empty-file removal, no-op-when-absent); `ruff check` clean on all 3
files (installer.py's 9 pre-existing lint findings are unchanged from
before this task — verified against the unmodified main repo — none of
them are on lines this task touched). No pre-existing test suite in this
repo exercises the installer module at all, so there was no regression
surface beyond these new tests.

**Deviations from spec**: `_uninstall_mcp_json` returns `str | None`
(`None` when there is nothing to report) instead of always returning a
message string as the task's illustrative snippet shows. Every OTHER
uninstall step in this module (`CLAUDE.md`, settings hooks/permissions,
slash command, git hook) only appends to the `actions` list when
something was actually removed — matching that, always-appending a
".mcp.json — not present" line would silently break the function's
existing "nothing to remove — integration not installed" summary
whenever `.mcp.json` was the only unmanaged artifact. This is a
consistency fix with the established local convention, not a design
change; the observable JSON file behavior is identical to the task's
snippet.
