# TASK-3213: Authorize the managed MCP servers in `.claude/settings.local.json`

**Feature**: FEAT-556 — `parrot claude install` seeds and authorizes the Parrot MCP servers
**Spec**: `sdd/specs/claude-install-mcp-autoenable.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3212
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 3. Claude Code treats project-scope `.mcp.json`
servers as untrusted until they are enabled, and the installer never enables
them. Verified on 2026-09-12 in the sibling `flowtask` repo: with a correct
`.mcp.json` and a correct `.parrot/mcp-toolkits.yaml`, `claude mcp list`
reported every parrot server as `⏸ Pending approval (run claude to approve)`,
the `sdd-worker` agent found no `mcp__parrot-sdd-coder__*` tools and fell back
to its sequential loop. Adding the names to `enabledMcpjsonServers` in
`.claude/settings.local.json` flipped all of them to `✔ Connected`.

Per-name approval is sufficient: removing `enableAllProjectMcpServers` while
keeping the name list left the listed servers connected and the unlisted ones
pending. The global switch must therefore NOT be written — it would also
authorize any future third-party entry in `.mcp.json`.

The installer already owns that file for permission rules
(`_install_permissions`, `installer.py:251-302`), so this task adds a sibling
step using the same `_load_settings` / `_write_settings` helpers.

---

## Scope

- Add `_managed_server_names(root)` returning `["wikitoolkit", "parrot-<name>", ...]`
  for every **enabled** toolkit section.
- Add `_install_mcp_approval(root)` merging those names into
  `enabledMcpjsonServers`, preserving foreign names and order.
- Add `_uninstall_mcp_approval(root)` removing exactly those names, and call it
  from `uninstall_claude_integration`.
- Report approval state and the seeded-YAML state from `integration_status`.
- Write `tests/knowledge/wiki/test_installer_mcp_approval.py`.

**NOT in scope**: calling `_install_mcp_approval` from
`install_claude_integration` and the `--approve-mcp` flag — that wiring is
TASK-3214 (this task leaves the function unreferenced by the installer flow).
Do not touch `permissions.allow` handling, and never write
`enableAllProjectMcpServers`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | MODIFY | `_managed_server_names`, `_install_mcp_approval`, `_uninstall_mcp_approval`, status keys |
| `tests/knowledge/wiki/test_installer_mcp_approval.py` | CREATE | Unit tests for approval install/uninstall/status |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.claude_code import assets      # verified: installer.py:33
from parrot.mcp.toolkit_config import load_toolkits_config  # verified: installer.py:361 (local import inside _install_mcp_json)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
def _load_settings(path: Path) -> Optional[dict[str, Any]]:   # line 159 — returns None when absent, raises RuntimeError on malformed JSON
def _write_settings(path: Path, settings: dict[str, Any]) -> None:  # line 183 — pretty JSON + trailing newline
def _install_permissions(root: Path) -> list[str]:            # line 251 — the sibling step to mirror, incl. its action phrasing (lines 294-301)
def _is_managed_toolkit_entry(entry, root, name) -> bool:     # line 304
def _install_mcp_json(root: Path) -> str:                     # line 321
    #   cfg = load_toolkits_config(root)                      # line 363
    #   enabled_names = {name for name, section in cfg.toolkits.items() if section.enabled}  # line 364
def uninstall_claude_integration(root: Path) -> list[str]:     # line 643
    #   settings.local.json permission removal block           # lines 720-741
    #   mcp_json_action = _uninstall_mcp_json(root)            # line 743
def integration_status(root: Path) -> dict[str, Any]:          # line 769
    #   permissions_installed = False                          # line 801
    #   mcp_json_installed = "wikitoolkit" in mcp_data.get("mcpServers", {})  # line 826
    #   return dict with keys: root, config, wiki_built, claude_md_section,
    #       pre_tool_use_hook, permissions, slash_command,
    #       git_post_commit_hook, mcp_json                     # lines 831-842
```

### Does NOT Exist
- ~~any `enabledMcpjsonServers` handling in `parrot/knowledge/wiki/`~~ — the
  string does not occur anywhere in the package; this task introduces it.
- ~~`assets.MANAGED_SERVER_NAMES` / any constant listing the servers~~ — the
  name set is derived at runtime from `load_toolkits_config`, never hardcoded.
- ~~`_write_settings` creating `.claude/`~~ — verify whether it makes parent
  directories before assuming it does; `_install_permissions` runs after
  `_install_settings_hook` (`installer.py:628-629`), which may be what creates
  the directory today.
- ~~a Claude Code setting named `enabledMcpServers` / `mcpServers` in
  settings.local.json~~ — the key that works is `enabledMcpjsonServers`
  (lower-case `json`), verified 2026-09-12 against `claude mcp list`.

---

## Implementation Notes

### Key Constraints
- **Never** write `enableAllProjectMcpServers` — spec §1 Non-Goals, and an
  explicit AC asserts its absence.
- Merge semantics: append missing names, keep existing order, never deduplicate
  or reorder foreign names.
- Uninstall removes only names this installer manages; a name the operator added
  by hand survives. Drop the key entirely when it becomes empty.
- Malformed input is loud: a non-list `enabledMcpjsonServers` raises
  `RuntimeError` naming the file, mirroring `_install_permissions`' guards
  (`installer.py:286-292`).
- `wikitoolkit` is part of the managed set — it is the one server the installer
  has always written (`assets.mcp_json_entry`, `assets.py:109`).

### References in Codebase
- `installer.py:251-302` — the function to mirror, including its "already
  allowed" vs "N rule(s) added" action phrasing.
- `installer.py:720-741` — the uninstall block to mirror for removal.

---

## Implementation Blueprint

### Steps (in order)
1. Add the three functions above `_is_managed_toolkit_entry` — *why*: they
   belong with the other settings writers and before the `.mcp.json` section
   that consumes the same enabled-name query.
2. Call `_uninstall_mcp_approval` from `uninstall_claude_integration`
   immediately before `_uninstall_mcp_json` — *why*: approval is meaningless
   once the entries are gone, and doing it first keeps the action order
   readable (settings → mcp.json).
3. Add the two status keys — *why*: AC requires `parrot claude status` to show
   both, and it is the only way an operator can tell approval happened without
   reading JSON.
4. Write the tests last, starting with the "never writes enable-all" one —
   *why*: it is the one regression that would silently widen trust.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` (MODIFY — new functions)
```python
# occurrences: 1 (verified: grep -c '^def _is_managed_toolkit_entry' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# BEFORE — insert above `def _is_managed_toolkit_entry(entry: Any, root: Path, name: str) -> bool:` (verified: installer.py:304)
def _managed_server_names(root: Path) -> list[str]:
    """Return the `.mcp.json` server names this installer manages.

    `["wikitoolkit"]` plus one `parrot-<name>` per ENABLED toolkit section —
    the same query `_install_mcp_json` reconciles with (verified:
    installer.py:363-364), so the two can never disagree.
    """
    from parrot.mcp.toolkit_config import load_toolkits_config

    cfg = load_toolkits_config(root)
    return ["wikitoolkit"] + [f"parrot-{name}" for name, section in sorted(cfg.toolkits.items()) if section.enabled]


def _install_mcp_approval(root: Path) -> str:
    """Merge the managed server names into `.claude/settings.local.json`.

    Claude Code leaves a project-scope `.mcp.json` server at "pending approval"
    until its name appears in `enabledMcpjsonServers`; an unapproved server is
    invisible to agents (verified 2026-09-12: sdd-worker saw no
    `mcp__parrot-sdd-coder__*` tools and fell back to its sequential loop).
    Never writes `enableAllProjectMcpServers`: per-name approval suffices and
    the global switch would also authorize unrelated third-party entries.

    Returns:
        One action string, phrased like `_install_permissions` (installer.py:294-301).

    Raises:
        RuntimeError: `enabledMcpjsonServers` exists but is not a JSON list.
    """
    local_path = root / ".claude" / "settings.local.json"
    local = _load_settings(local_path) or {}
    names = local.get("enabledMcpjsonServers")
    if names is None:
        names = local["enabledMcpjsonServers"] = []
    if not isinstance(names, list):
        raise RuntimeError(f"{local_path}: 'enabledMcpjsonServers' is not a list")
    missing = [n for n in _managed_server_names(root) if n not in names]
    if not missing:
        return ".claude/settings.local.json — MCP servers already authorized"
    names.extend(missing)
    _write_settings(local_path, local)
    return f".claude/settings.local.json — {len(missing)} MCP server(s) authorized ({', '.join(missing)})"


def _uninstall_mcp_approval(root: Path) -> str | None:
    """Remove only the managed names from `enabledMcpjsonServers`.

    Returns:
        An action string, or None when there was nothing to remove.
    """
    # FILL IN: load, filter out _managed_server_names(root), drop the key when
    # it becomes empty, write only on change — bounded by AC "foreign names are
    # kept"; note that a disabled/removed section means a name that is no
    # longer in _managed_server_names, so ALSO strip any `parrot-` name whose
    # section no longer exists, or uninstall would leave stale approvals behind
```
**Why this shape**: `_managed_server_names` is the single source of truth shared
by install, uninstall and status — do not inline the query a second time.
`_install_mcp_approval` returns a single string (not a list) because
`install_claude_integration` appends it with `actions.append(...)` like
`_install_mcp_json`, not `extend`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` (MODIFY — uninstall)
```python
# occurrences: 1 (verified: grep -c 'mcp_json_action = _uninstall_mcp_json(root)' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# BEFORE — insert above `mcp_json_action = _uninstall_mcp_json(root)` (verified: installer.py:743)
    approval_action = _uninstall_mcp_approval(root)
    if approval_action:
        actions.append(approval_action)
```
**Why**: mirrors the existing `mcp_json_action` pattern two lines below, so the
None-means-nothing-to-do convention stays consistent.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` (MODIFY — status)
```python
# occurrences: 1 (verified: grep -c '        "mcp_json": mcp_json_installed,' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# AFTER — insert below `        "mcp_json": mcp_json_installed,` (verified: installer.py:841)
        "mcp_servers_authorized": mcp_approved,
        "toolkits_yaml": (root / ".parrot" / "mcp-toolkits.yaml").exists(),
```
**Why**: two new read-only keys; `mcp_approved` is computed earlier in the
function next to `permissions_installed` (`installer.py:801`).
**FILL IN**: compute `mcp_approved` — True when every
`_managed_server_names(root)` entry appears in the file's
`enabledMcpjsonServers`; bounded by "status is read-only and must not raise"
(`integration_status` swallows `WikiConfigError` at `installer.py:779-782`, so
wrap the load the same way).

### FILL IN checklist
- [ ] `installer.py::_uninstall_mcp_approval` — removal + stale-name handling; bounded by "foreign names are kept"
- [ ] `installer.py::integration_status` — `mcp_approved` computation that cannot raise

---

## Acceptance Criteria

- [ ] After `_install_mcp_approval(root)`, `enabledMcpjsonServers` contains
      `wikitoolkit` plus one `parrot-<name>` per enabled section
- [ ] `enableAllProjectMcpServers` is absent from the written settings
- [ ] A foreign name already present survives, and order is preserved
- [ ] Second call returns the "already authorized" action and leaves the file
      byte-identical
- [ ] A non-list `enabledMcpjsonServers` raises `RuntimeError` naming the file
- [ ] Uninstall removes only managed names, keeps foreign ones, and drops the
      key when empty
- [ ] `integration_status(root)` exposes `mcp_servers_authorized` and
      `toolkits_yaml`, and never raises on a malformed settings file
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_installer_mcp_approval.py -v`
      and `pytest tests/knowledge/wiki/test_claude_code.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py`

---

## Test Specification

```python
# tests/knowledge/wiki/test_installer_mcp_approval.py
import json

import pytest
from parrot.knowledge.wiki.claude_code.installer import (
    _install_mcp_approval,
    _managed_server_names,
    _uninstall_mcp_approval,
    integration_status,
)


def _local(root):
    return json.loads((root / ".claude" / "settings.local.json").read_text())


def test_approval_adds_managed_names(tmp_root_with_config):
    _install_mcp_approval(tmp_root_with_config)
    assert set(_managed_server_names(tmp_root_with_config)) <= set(
        _local(tmp_root_with_config)["enabledMcpjsonServers"]
    )


def test_approval_never_writes_enable_all(tmp_root_with_config):
    _install_mcp_approval(tmp_root_with_config)
    assert "enableAllProjectMcpServers" not in _local(tmp_root_with_config)


def test_approval_preserves_foreign_names(tmp_root_with_config):
    # FILL IN: pre-seed enabledMcpjsonServers with "some-other-server", install,
    # assert it is still present and still first


def test_approval_idempotent(tmp_root_with_config):
    # FILL IN: install twice, compare file bytes and assert the second action
    # string says "already authorized"


def test_approval_rejects_non_list_key(tmp_root_with_config):
    # FILL IN: write a string value, assert RuntimeError mentioning the path


def test_uninstall_removes_only_managed_names(tmp_root_with_config):
    # FILL IN: install, add a foreign name, uninstall approval, assert only the
    # foreign name remains


def test_status_reports_approval_and_seeded_yaml(tmp_root_with_config):
    status = integration_status(tmp_root_with_config)
    assert "mcp_servers_authorized" in status and "toolkits_yaml" in status
```
Reuse the `tmp_root_with_config` fixture from
`tests/knowledge/wiki/test_installer_toolkit_entries.py` (move it into a
`conftest.py` only if import-sharing proves awkward).

---

## Agent Instructions

1. **Read the spec** §3 Module 3 and §1 Problem Statement item 2.
2. **Check dependencies** — TASK-3212 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read `installer.py:251-302` and the
   status return dict; line numbers shift as this task adds code.
4. **Update status** in `sdd/tasks/index/claude-install-mcp-autoenable.json` → `"in-progress"`.
5. **Implement** from the blueprint; complete every `# FILL IN:` marker.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3213-mcp-approval.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-coder (dispatched by sdd-worker orchestrator, FEAT-549)
**Date**: 2026-09-12
**Notes**: Added `_managed_server_names`, `_install_mcp_approval`, and
`_uninstall_mcp_approval` to `installer.py`; wired the uninstall step into
`uninstall_claude_integration`; exposed `mcp_servers_authorized` and
`toolkits_yaml` in `integration_status`. `enableAllProjectMcpServers` is
never written. All 52 tests across
`tests/knowledge/wiki/test_installer_mcp_approval.py` (7) and
`tests/knowledge/wiki/test_claude_code.py` (45) pass; `ruff check` on
`installer.py` is clean.
**Deviations from spec**: none

Seat: gemini · Backend: google-compat · Model: gemini-3.5-flash · Attempts: 1 · Duration: 60.354s · Tokens: 564014 in / 4887 out
