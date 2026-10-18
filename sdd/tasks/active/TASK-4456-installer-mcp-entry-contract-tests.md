# TASK-4456: Installer `.mcp.json` tests pin the absolute-path and foreign-entry contract

**Feature**: FEAT-700 — Hermetic, current expectations for the package-tree wiki tests
**Spec**: `sdd/specs/fixgroup-09687c688868.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 1h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: issue:66599d4e8c84

---

## Context

Ledger fix lane (`/sdd-fix`, fixgroup:09687c688868). Two installer tests
pin a contract that FEAT-485/570 and TASK-3212 changed on purpose:
`assets.mcp_json_entry(root)` writes an **absolute** `wikitoolkit` path
(`assets.py:119-125`), and a `wikitoolkit` entry whose command does not end
with `wikitoolkit` (or whose args are not `["mcp"]`) is *foreign* and left
untouched (`installer.py:731`, `_is_wikitoolkit_entry` at `:753`).
Implements spec §3 M2 (cluster C).

---

## Scope

- `test_install_creates_mcp_json`: assert the managed shape, not a bare
  command string.
- `test_install_updates_stale_entry`: seed a managed-shape entry with a
  stale path and assert it is refreshed to the current entry.
- Add `test_install_leaves_foreign_wikitoolkit_entry_untouched`.

**NOT in scope**: installer source; toolkit-entry reconciliation tests;
remote/HTTP entries.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py` | MODIFY | three tests in `TestMCPJsonInstall` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.claude_code import assets  # verified: assets.py:119 def mcp_json_entry(root: Path) -> dict
from parrot.knowledge.wiki.claude_code.installer import install_claude_integration  # verified: test_installer_mcp.py:6
```

### Existing Signatures to Use
```python
# assets.py:119
def mcp_json_entry(root: Path) -> dict:  # {"command": resolve_wikitoolkit_bin(root), "args": ["mcp"], "env": {}}
# installer.py:753
def _is_wikitoolkit_entry(entry: Any) -> bool:  # stdio: command.endswith("wikitoolkit") and args == ["mcp"]
# test_installer_mcp.py:15 fixture repo_root(tmp_path) -> tmp_path with .git/ and .parrot/
```

### Does NOT Exist
- ~~`install_claude_integration(repo_root, command="wikitoolkit")`~~ — no
  command override; the entry is always `assets.mcp_json_entry(root)`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py#mcp_json_entry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_is_wikitoolkit_entry"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Compare against `assets.mcp_json_entry(repo_root)` rather than a
  hardcoded path: the resolved binary depends on the machine.
- Keep the other `TestMCPJsonInstall` tests untouched.

---

## Implementation Blueprint

### `packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py` (MODIFY)
```python
# add import next to the installer import:
from parrot.knowledge.wiki.claude_code import assets

# occurrences: 1 (verified: grep -c 'def test_install_creates_mcp_json' <path>)
# REPLACE the whole test (lines 40-47):
    def test_install_creates_mcp_json(self, repo_root):
        install_claude_integration(repo_root)
        mcp_json = repo_root / ".mcp.json"
        assert mcp_json.exists()
        data = json.loads(mcp_json.read_text())
        entry = data["mcpServers"]["wikitoolkit"]
        # TASK-3212: the managed entry pins the resolved binary, never a bare name.
        assert entry["command"].endswith("wikitoolkit")
        assert entry["args"] == ["mcp"]
        assert entry == assets.mcp_json_entry(repo_root)

# occurrences: 1 (verified: grep -c 'def test_install_updates_stale_entry' <path>)
# REPLACE the whole test (lines 63-68):
    def test_install_updates_stale_entry(self, repo_root):
        # Managed shape (ends with "wikitoolkit", args == ["mcp"]) but a stale path.
        mcp_json = repo_root / ".mcp.json"
        stale = {"command": "/old/venv/bin/wikitoolkit", "args": ["mcp"], "env": {}}
        mcp_json.write_text(json.dumps({"mcpServers": {"wikitoolkit": stale}}))
        install_claude_integration(repo_root)
        data = json.loads(mcp_json.read_text())
        assert data["mcpServers"]["wikitoolkit"] == assets.mcp_json_entry(repo_root)

    def test_install_leaves_foreign_wikitoolkit_entry_untouched(self, repo_root):
        # FEAT-485/570: an entry we did not write is never overwritten.
        mcp_json = repo_root / ".mcp.json"
        foreign = {"command": "old-stale-command"}
        mcp_json.write_text(json.dumps({"mcpServers": {"wikitoolkit": foreign}}))
        install_claude_integration(repo_root)
        data = json.loads(mcp_json.read_text())
        assert data["mcpServers"]["wikitoolkit"] == foreign
```

---

## Acceptance Criteria

- [ ] AC1: `TestMCPJsonInstall` passes in full (the two fixed tests + the new one + the untouched ones).
- [ ] AC2: no hardcoded absolute path in the file.
- [ ] No linting errors.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py -q -p no:cacheprovider -o addopts=""`

---

## Test Specification

See blueprint.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug fixgroup-09687c688868 --feature-id FEAT-700`)
2. **Read the spec** for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing any code
5. **Update status** in `sdd/tasks/index/fixgroup-09687c688868.json` → `"in-progress"` and commit only that index file
6. **Implement** from the Implementation Blueprint
7. **Verify** acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the one listed file
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4456 fixgroup-09687c688868 verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*
