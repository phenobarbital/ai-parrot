# TASK-5543: Run the shell prefix from an immutable copy in the session directory

**Feature**: FEAT-881 — Legacy shell-prefix fixes
**Spec**: `sdd/specs/scripts-native-claude-sandbox-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5542
**Assigned-to**: unassigned
**Discovered-from**: `issue:975e2aa0bfb4`

---

## Context

Spec §2 M2. The `prefix` stub execs `shell_prefix.py` next to `__file__`; when the launcher runs from a feature worktree that file and `worktree_environment.py` are session-writable and run unsandboxed (sandbox escape).

---

## Scope

- In `prepare_shell_prefix`, copy `shell_prefix.py` and `worktree_environment.py` into the session directory (mode `0400`).
- Point the `prefix` stub at `<session>/shell_prefix.py`.
- Record the policy `worktree` as `_native_roots(cwd)[0]` (the frozen root; spec §2 M3 last-but-one bullet).
- Tests: copies exist, are byte-identical and `0400`; the stub names the copy; the copy runs a pass-through command in a subprocess with `-E -s`.

**NOT in scope**: `owner.pid` and session expiry (TASK-5545); hook-side validation (TASK-5544).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` | MODIFY | copy runtime, stub target, worktree root |
| `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` | MODIFY | copy tests |

---

## Codebase Contract (Anti-Hallucination)

Verified against `2d45f09fd9`.

### Verified Imports
```python
# No new imports from other packages: both scripts are standard-library only.
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py
def _native_roots(cwd: Path) -> tuple[Path, Path, Path]:  # line 147
def _prefix_writable_roots(cwd: Path) -> tuple[Path, ...]:  # line 920
def prepare_shell_prefix(cwd, settings, mode, *, rtk) -> dict[str, str]:  # line 1007
#   session_dir.mkdir(mode=0o700)                                          # line 1032
#   worktree=str(_canonical(cwd)),                                         # line 1041
#   shell_prefix = Path(__file__).resolve().with_name("shell_prefix.py")   # line 1063
# packages/ai-parrot/src/parrot/sdd/scripts/shell_prefix.py:23-26 — script mode imports `worktree_environment` from its own directory (sys.path[0])
```

### Does NOT Exist
- ~~any copy of the prefix runtime in the session directory today (only `policy.json` and `prefix`)~~
- ~~a `shell_prefix.py` import of anything other than `worktree_environment` and the standard library~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#prepare_shell_prefix",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#_native_roots"
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
1. Copy both runtime files with `shutil.copyfile`, then `chmod(0o400)` — *why*: the state root is checked to be outside every writable root, so the copies cannot be edited by the session.
2. Build the stub from the copy's path — *why*: this is the file that runs outside `bwrap` on every call.
3. Record `worktree` from `_native_roots(cwd)[0]` — *why*: TASK-5544's hook compares it with the frozen root.

### `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'shell_prefix = Path(__file__).resolve().with_name("shell_prefix.py")')
# REPLACE that line (verified: packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:1063)
    scripts = Path(__file__).resolve().parent
    for name in ("shell_prefix.py", "worktree_environment.py"):
        runtime = session_dir / name
        shutil.copyfile(scripts / name, runtime)
        runtime.chmod(0o400)
    shell_prefix = session_dir / "shell_prefix.py"
```
```python
# occurrences: 1 (verified: grep -cF 'worktree=str(_canonical(cwd)),')
# REPLACE that line (verified: packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:1041)
        worktree=str(_native_roots(cwd)[0]),
```
**Why**: everything the prefix trusts must live outside all writable roots; only the policy and stub did.

### `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` (MODIFY)
```python
# FILL IN: tests listed under Test Specification — bounded by AC 4 of the spec
```

### FILL IN checklist
- [ ] the two tests

---

## Acceptance Criteria

- [ ] `<session>/shell_prefix.py` and `<session>/worktree_environment.py` exist with mode `0400` and source bytes.
- [ ] The `prefix` stub contains the session copy's path and not the source tree's.
- [ ] Running the stub with a recorded hook command executes it (exit 0) from a subprocess.
- [ ] `ruff check` is clean on the changed files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`

---

## Test Specification

```python
def test_prepare_shell_prefix_copies_runtime_into_session(linked, monkeypatch, tmp_path): ...
def test_prefix_stub_runs_passthrough_from_session_copy(linked, monkeypatch, tmp_path): ...
```

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug scripts-native-claude-sandbox-fixes --feature-id FEAT-881`).
2. Check every `Depends-on` task is `done` in `sdd/tasks/index/scripts-native-claude-sandbox-fixes.json`.
3. Verify the Codebase Contract, mark the task `in-progress`, implement from the blueprint.
4. Run the Validation Commands, commit only the listed files.
5. Close with `parrot sdd task close TASK-5543 scripts-native-claude-sandbox-fixes verified`, fill the Completion Note, commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
