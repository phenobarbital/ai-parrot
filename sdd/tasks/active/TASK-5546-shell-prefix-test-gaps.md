# TASK-5546: Close shell-prefix test gaps (policy validation, live write assertion)

**Feature**: FEAT-881 — Legacy shell-prefix fixes
**Spec**: `sdd/specs/scripts-native-claude-sandbox-fixes.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5544
**Assigned-to**: unassigned
**Discovered-from**: `issue:93ac744f0a74`

---

## Context

Spec §2 M5 (ledger sub-item 8). `load_policy`'s rejection paths and the live test's positive path are untested.

---

## Scope

- `test_shell_prefix.py`: symlinked policy, invalid JSON, non-object JSON, unknown key, wrong field type → exit 2, nothing exec'd.
- `test_shell_prefix_live.py`: assert a file written by the session inside the worktree exists, and that the MCP process recorded an empty token.

**NOT in scope**: Any source change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/sdd/test_shell_prefix.py` | MODIFY | validation cases |
| `packages/ai-parrot/tests/flows/dev_loop/test_shell_prefix_live.py` | MODIFY | positive write + MCP token |

---

## Codebase Contract (Anti-Hallucination)

Verified against `2d45f09fd9`.

### Verified Imports
```python
# No new imports from other packages: both scripts are standard-library only.
```

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/sdd/test_shell_prefix.py
def _write_policy(tmp_path, **overrides) -> tuple[Path, dict]:  # line 19
def _capture_exec(monkeypatch) -> dict:  # line 36
def test_errors_exit_2_and_exec_nothing(...)  # line 168 — parametrized (arguments, policy, mode, bwrap_missing)
# packages/ai-parrot/tests/flows/dev_loop/test_shell_prefix_live.py
def test_legacy_prefix_live_session(tmp_path, monkeypatch) -> None:  # line 33; hook_token / mcp_token files at 47-48
```

### Does NOT Exist
- ~~a symlink or invalid-JSON case in `test_errors_exit_2_and_exec_nothing`~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/sdd/test_shell_prefix.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_shell_prefix_live.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/shell_prefix.py#load_policy"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Standard library only; the module also runs as a script (keep the `if __package__: … else: …` import pairs).
- Google-style docstrings and type hints on every new function; 120-column lines.
- These files are the sandbox's own policy: implement from a host session, never a sandboxed `sdd-worker`.
- In a worktree run pytest with an ABSOLUTE `PYTHONPATH=<worktree>/packages/ai-parrot/src`.

---

## Implementation Blueprint

### Steps (in order)
1. Add a dedicated parametrized test for raw policy contents — *why*: the existing parametrization only merges dict overrides and cannot express invalid JSON or a symlink.
2. Extend the live test — *why*: a model refusal currently passes it vacuously.

### `packages/ai-parrot/tests/sdd/test_shell_prefix.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'def test_script_mode_does_not_import_parrot() -> None:')
# BEFORE — insert above that test
@pytest.mark.parametrize("contents", ["{not json", "[]", '{"schema_version": 1}'])
def test_malformed_policy_contents_exit_2(tmp_path, monkeypatch, capsys, contents) -> None:
    """Policies that are not a complete JSON object block execution."""
    # FILL IN: write contents with 0o600, run main(["echo safe"]), assert exit 2 and no exec — bounded by AC of this task
```
### `packages/ai-parrot/tests/flows/dev_loop/test_shell_prefix_live.py` (MODIFY)
```python
# FILL IN: positive in-worktree write assertion + empty MCP token assertion — bounded by spec §2 M5
```
**Why**: tests only; no behaviour changes.

### FILL IN checklist
- [ ] malformed-contents test
- [ ] symlink / unknown-key / wrong-type cases
- [ ] live assertions

---

## Acceptance Criteria

- [ ] Each malformed policy exits 2 with `sdd shell prefix:` on stderr and executes nothing.
- [ ] The live test fails when the session writes nothing inside the worktree.
- [ ] The live test still skips without `claude` or `bwrap`.
- [ ] `ruff check` is clean on the changed files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_shell_prefix.py -q`

---

## Test Specification

```python
def test_malformed_policy_contents_exit_2(...): ...
def test_symlinked_policy_exit_2(...): ...
def test_policy_with_unknown_key_or_wrong_type_exit_2(...): ...
```

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug scripts-native-claude-sandbox-fixes --feature-id FEAT-881`).
2. Check every `Depends-on` task is `done` in `sdd/tasks/index/scripts-native-claude-sandbox-fixes.json`.
3. Verify the Codebase Contract, mark the task `in-progress`, implement from the blueprint.
4. Run the Validation Commands, commit only the listed files.
5. Close with `parrot sdd task close TASK-5546 scripts-native-claude-sandbox-fixes verified`, fill the Completion Note, commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
