# TASK-5544: Hook validates the prefix policy; token reaches hooks only

**Feature**: FEAT-881 — Legacy shell-prefix fixes
**Spec**: `sdd/specs/scripts-native-claude-sandbox-fixes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:93ac744f0a74`

---

## Context

Spec §2 M3 (ledger sub-items 1, 3, 4). The hook trusts any policy file whose sha256 equals the token, and the prefix hands that token to MCP servers as well as hooks.

---

## Scope

- `_shell_prefix_policy()` loads through `shell_prefix.load_policy`, compares digest with the token, and returns `PrefixPolicy | None`; also `None` when `PARROT_SDD_SANDBOX_ROOTS` is set and its first entry differs from `policy.worktree`.
- Import `shell_prefix` lazily in both package and script modes.
- `_wrap_bash` uses `policy.rtk` / `policy.mode`.
- `shell_prefix.main` sets the token only for arguments in `policy.hook_commands`.
- Rewrite the hook tests that use minimal policies; add rejection tests and the MCP-no-token test.

**NOT in scope**: Launcher changes (TASK-5542/5543/5545); the extra `load_policy` schema tests (TASK-5546).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` | MODIFY | validated policy loader |
| `packages/ai-parrot/src/parrot/sdd/scripts/shell_prefix.py` | MODIFY | hook-only token |
| `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` | MODIFY | hook tests |
| `packages/ai-parrot/tests/sdd/test_shell_prefix.py` | MODIFY | token test |

---

## Codebase Contract (Anti-Hallucination)

Verified against `2d45f09fd9`.

### Verified Imports
```python
# No new imports from other packages: both scripts are standard-library only.
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/scripts/shell_prefix.py
class PrefixPolicy: schema_version, mode, worktree, hook_commands, mcp_argv, rtk  # line 36 (frozen dataclass)
def load_policy(path: str | Path) -> tuple[PrefixPolicy, str]:  # line 67 — raises ValueError / OSError
def main(argv: Sequence[str] | None = None) -> NoReturn:  # line 193; `if decision.kind == "passthrough":` at 213
# packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py
def _load_native_sandbox() -> Any:  # line 604 — the lazy sibling-import pattern to copy
LAUNCHER_MARKERS = ("PARROT_SDD_SANDBOX_ROOTS", "PARROT_SDD_CACHE_DIR")  # line 625
def _shell_prefix_policy() -> dict[str, Any] | None:  # line 652
#   `if not (prefix_policy and prefix_policy.get("rtk") is True):`                                   # line 696
#   `if backend == "bubblewrap" and (policy := _shell_prefix_policy()) and policy.get("mode") == "legacy":`  # line 714
# packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py: tests using the token env at lines ≈ 940–1010
```

### Does NOT Exist
- ~~an import of `shell_prefix` inside `worktree_environment.py` (the import goes the other way today)~~
- ~~a `PrefixDecision` field that distinguishes hook from MCP pass-through~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/shell_prefix.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_shell_prefix.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#_shell_prefix_policy",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#_wrap_bash",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/shell_prefix.py#load_policy",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/shell_prefix.py#main"
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
1. Add `_load_shell_prefix()` next to `_load_native_sandbox` — *why*: `shell_prefix` imports this module, so the import must be lazy and, in script mode, pre-seed `sys.modules['worktree_environment']`.
2. Rewrite `_shell_prefix_policy` around `load_policy` — *why*: one validator for the prefix and the hook.
3. Switch `_wrap_bash` to attributes — *why*: the return type is now a dataclass.
4. Narrow the token in `shell_prefix.main` — *why*: the token is the hook's proof; MCP servers have no use for it.
5. Fix the existing tests to write complete `0600` policies.

### `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'def _shell_prefix_policy() -> dict[str, Any] | None:')
# REPLACE the whole function (verified: packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:652-665)
def _load_shell_prefix() -> Any:
    """Return the sibling ``shell_prefix`` module without importing Parrot in script mode."""
    if __package__:
        from . import shell_prefix
    else:  # run as a script: this file's directory is sys.path[0]
        sys.modules.setdefault("worktree_environment", sys.modules[__name__])
        import shell_prefix
    return shell_prefix


def _shell_prefix_policy() -> Any | None:
    """Return the validated, token-authenticated shell-prefix policy, or ``None`` without proof."""
    policy_path = os.environ.get("PARROT_SDD_SHELL_PREFIX_POLICY")
    token = os.environ.get("PARROT_SDD_SHELL_PREFIX_TOKEN")
    if not policy_path or not token:
        return None
    try:
        policy, digest = _load_shell_prefix().load_policy(policy_path)
    except (OSError, ValueError):
        return None
    # FILL IN: reject digest != token, and a frozen root (first PARROT_SDD_SANDBOX_ROOTS entry) != policy.worktree
    #          — bounded by spec §2 M3
    return policy
```
```python
# occurrences: 1 each (verified: grep -cF at packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:696 and :714)
    if not (prefix_policy and prefix_policy.rtk):
    if backend == "bubblewrap" and (policy := _shell_prefix_policy()) and policy.mode == "legacy":
```
### `packages/ai-parrot/src/parrot/sdd/scripts/shell_prefix.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'if decision.kind == "passthrough":')
# REPLACE that line (verified: packages/ai-parrot/src/parrot/sdd/scripts/shell_prefix.py:213)
        if decision.kind == "passthrough" and arguments[0] in policy.hook_commands:
```
**Why**: full validation closes the "any file with a matching hash" hole; the token stays a hook-only proof.

### `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` / `packages/ai-parrot/tests/sdd/test_shell_prefix.py` (MODIFY)
```python
# FILL IN: tests listed under Test Specification — bounded by AC 5–6 of the spec
```

### FILL IN checklist
- [ ] digest and frozen-root checks
- [ ] updated and new tests

---

## Acceptance Criteria

- [ ] A valid policy with the right token is honoured (no `bwrap` rewrite).
- [ ] Forged token, bad schema, group-writable file, symlink, or frozen-root mismatch → the hook wraps in `bwrap`.
- [ ] MCP pass-through runs without `PARROT_SDD_SHELL_PREFIX_TOKEN`; hook pass-through runs with it.
- [ ] `worktree_environment.py` still imports with `python -E -s` as a script, without `parrot`.
- [ ] `ruff check` is clean on the changed files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_shell_prefix.py -q`

---

## Test Specification

```python
def test_hook_rejects_policy_that_fails_validation(tmp_path, monkeypatch): ...   # schema / perms / symlink
def test_hook_rejects_policy_for_another_worktree(tmp_path, monkeypatch): ...
def test_mcp_passthrough_receives_no_token(tmp_path, monkeypatch): ...
```

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug scripts-native-claude-sandbox-fixes --feature-id FEAT-881`).
2. Check every `Depends-on` task is `done` in `sdd/tasks/index/scripts-native-claude-sandbox-fixes.json`.
3. Verify the Codebase Contract, mark the task `in-progress`, implement from the blueprint.
4. Run the Validation Commands, commit only the listed files.
5. Close with `parrot sdd task close TASK-5544 scripts-native-claude-sandbox-fixes verified`, fill the Completion Note, commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
