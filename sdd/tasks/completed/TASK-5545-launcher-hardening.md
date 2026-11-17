# TASK-5545: Launcher hardening: version gate, session expiry, agent hooks, inherited prefix

**Feature**: FEAT-881 — Legacy shell-prefix fixes
**Spec**: `sdd/specs/scripts-native-claude-sandbox-fixes.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5543
**Assigned-to**: unassigned
**Discovered-from**: `issue:93ac744f0a74`

---

## Context

Spec §2 M4 (ledger sub-items 2, 5, 6, 7).

---

## Scope

- `MIN_PREFIX_CLAUDE_VERSION = (2, 1, 321)` and `_claude_version(claude)`; refuse a prefix launch (exit 1) below it or when unparseable.
- Write `owner.pid` in the prefix session directory; `_remove_expired_prefix_sessions` keeps directories with a live owner.
- `_agent_hook_commands` reads `command:` lines only inside the frontmatter's top-level `hooks:` block.
- Remove `CLAUDE_CODE_SHELL_PREFIX` / `PARROT_SDD_SHELL_PREFIX_POLICY` from the child env when no prefix is prepared; always remove `PARROT_SDD_SHELL_PREFIX_TOKEN`.
- Tests for each.

**NOT in scope**: MCP config (TASK-5542); runtime copy (TASK-5543).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` | MODIFY | four hardening changes |
| `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` | MODIFY | unit tests |
| `packages/ai-parrot/tests/sdd/test_sdd_launch.py` | MODIFY | launch tests |

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
def _process_is_alive(pid: int) -> bool:  # line 875
def _agent_hook_commands(path: Path) -> list[str]:  # line 957 — regex over the whole frontmatter
def _remove_expired_prefix_sessions(state_root: Path) -> None:  # line 988 — 7-day cutoff on dir mtime
def prepare_shell_prefix(...)  # line 1007; `session_dir.mkdir(mode=0o700)` at 1032
def launch_worker(...)  # line 1077; `if mode == "legacy" or (not degraded and _NATIVE_PREFIX_RTK_QUALIFIED):` at 1183
# `subprocess` is already imported (line 19)
```

### Does NOT Exist
- ~~any Claude Code version check in the launcher~~
- ~~an `owner.pid` in prefix session directories (`_allocate_session_cache` writes one for the cache only)~~

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
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_sdd_launch.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#launch_worker",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#_agent_hook_commands",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#_remove_expired_prefix_sessions",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#_process_is_alive",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#prepare_shell_prefix"
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
1. Add `_claude_version` and gate the prefix branch — *why*: the prefix boundary was verified live only on 2.1.321; an older CLI may run hooks through the prefix but not Bash.
2. Write `owner.pid` and honour it in cleanup — *why*: `execvpe` keeps the launcher pid for Claude, so a live pid means a live session.
3. Scope `_agent_hook_commands` to the `hooks:` block — *why*: any other `command:` key would be allowlisted to run unsandboxed.
4. Strip inherited prefix variables — *why*: a parent session's prefix must not leak into a native launch.

### `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'def _remove_expired_prefix_sessions(state_root: Path) -> None:')
# BEFORE — insert above that function (verified: packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:988)
MIN_PREFIX_CLAUDE_VERSION = (2, 1, 321)


def _claude_version(claude: str) -> tuple[int, int, int] | None:
    """Return the Claude Code version reported by ``claude --version``, or ``None`` when unknown."""
    # FILL IN: subprocess.run([claude, "--version"], timeout=10), parse the first X.Y.Z — bounded by spec §2 M4
```
```python
# occurrences: 1 (verified: grep -cF 'if mode == "legacy" or (not degraded and _NATIVE_PREFIX_RTK_QUALIFIED):')
# INSIDE that branch (verified: packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:1183), before prepare_shell_prefix:
#   FILL IN: version gate -> print "launch_worker: shell prefix unavailable (…)" and return 1
# ELSE branch: FILL IN: env.pop of the inherited prefix variables — bounded by spec §2 M4
```
```python
# occurrences: 1 (verified: grep -cF 'session_dir.mkdir(mode=0o700)')
# AFTER — insert below that line (verified: packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:1032)
    (session_dir / "owner.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
```
**Why**: each change removes one way for the legacy boundary to be absent or bypassed without notice.

### `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` / `packages/ai-parrot/tests/sdd/test_sdd_launch.py` (MODIFY)
```python
# FILL IN: tests listed under Test Specification — bounded by AC 7–10 of the spec
```

### FILL IN checklist
- [ ] `_claude_version` body
- [ ] gate and env stripping in `launch_worker`
- [ ] `owner.pid` check in cleanup
- [ ] `hooks:` block parsing
- [ ] tests

---

## Acceptance Criteria

- [ ] Legacy launch with version `2.1.320` or unparseable output returns 1 and never calls `execvpe`.
- [ ] An 8-day-old session directory with a live `owner.pid` survives; one with a dead pid is removed.
- [ ] A `command:` line outside `hooks:` in the agent frontmatter is not collected.
- [ ] A native launch drops an inherited `CLAUDE_CODE_SHELL_PREFIX`.
- [ ] `ruff check` is clean on the changed files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_sdd_launch.py -q`

---

## Test Specification

```python
def test_claude_version_parses_and_gates_legacy_launch(tmp_path, monkeypatch, capsys): ...
def test_expired_prefix_session_with_live_owner_survives(tmp_path): ...
def test_agent_hook_commands_only_inside_hooks_block(tmp_path): ...
def test_native_launch_drops_inherited_shell_prefix(tmp_path, monkeypatch): ...
```

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug scripts-native-claude-sandbox-fixes --feature-id FEAT-881`).
2. Check every `Depends-on` task is `done` in `sdd/tasks/index/scripts-native-claude-sandbox-fixes.json`.
3. Verify the Codebase Contract, mark the task `in-progress`, implement from the blueprint.
4. Run the Validation Commands, commit only the listed files.
5. Close with `parrot sdd task close TASK-5545 scripts-native-claude-sandbox-fixes verified`, fill the Completion Note, commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Code host session (/sdd-fix agent:sdd-fix:b338296a)
**Date**: 2026-11-12
**Notes**: Added MIN_PREFIX_CLAUDE_VERSION and _claude_version (prefix launches below 2.1.321 or with an unknown version exit 1); owner.pid in prefix session directories and a liveness check before expiry; _agent_hook_commands limited to the frontmatter hooks: block; inherited CLAUDE_CODE_SHELL_PREFIX / policy dropped when no prefix is prepared and the token dropped always. 197 tests pass; the real CLI here reports 2.1.322.

**Deviations from spec**: none
