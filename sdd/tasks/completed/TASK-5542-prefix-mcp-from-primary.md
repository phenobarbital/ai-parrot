# TASK-5542: Legacy prefix reads MCP servers from the primary checkout

**Feature**: FEAT-881 — Legacy shell-prefix fixes
**Spec**: `sdd/specs/scripts-native-claude-sandbox-fixes.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:1f3a8f42fbc6`

---

## Context

Spec §2 M1. `prepare_shell_prefix` builds the MCP pass-through allowlist from `<worktree>/.mcp.json`, which is gitignored and so absent in a fresh worktree: every MCP server is then wrapped in `bwrap` and fails.

---

## Scope

- Add `prefix_mcp_config(cwd)` returning `<primary>/.mcp.json` when it holds a non-empty `mcpServers` object.
- Make `prepare_shell_prefix` build `mcp_argv` from that path only (empty when `None`).
- In `launch_worker`'s prefix branch add `--mcp-config <path> --strict-mcp-config`, or `--strict-mcp-config` alone plus a stderr warning when there is no config; emit them right after `--agent sdd-worker`.
- Add `--strict-mcp-config` to `_REJECTED_OPTIONS`.
- Tests: primary-only config, worktree-planted config ignored, missing config warns, argv order.

**NOT in scope**: Copying the prefix runtime (TASK-5543); version gate and env stripping (TASK-5545).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` | MODIFY | MCP source + launcher flags |
| `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` | MODIFY | policy tests |
| `packages/ai-parrot/tests/sdd/test_sdd_launch.py` | MODIFY | argv tests |

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
def _native_roots(cwd: Path) -> tuple[Path, Path, Path]:  # line 147 — (root, git_dir, primary)
_REJECTED_OPTIONS = (...)  # line 691
def _load_json(path: Path) -> dict[str, Any]:  # line 948 — absent/malformed -> {}
def _prefix_mcp_argv(path: Path) -> list[list[str]]:  # line 973
def prepare_shell_prefix(cwd: Path, settings: dict, mode: str, *, rtk: bool) -> dict[str, str]:  # line 1007
def launch_worker(argv, *, cwd=None, initial_prompt=None, base_env=None) -> int:  # line 1077
```

### Does NOT Exist
- ~~`prefix_mcp_config` — this task creates it~~
- ~~any read of the primary checkout's `.mcp.json` in the launcher~~
- ~~a `--mcp-config` flag emitted by the launcher today (it is only rejected from callers)~~

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
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#prepare_shell_prefix",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#launch_worker",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#_prefix_mcp_argv",
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
1. Add `prefix_mcp_config` above `prepare_shell_prefix` — *why*: one resolver shared by the policy and the launcher keeps them identical.
2. Swap the `mcp_argv=` line to use it — *why*: the worktree file is worker-writable and usually absent.
3. Emit the CLI flags in the prefix branch of `launch_worker` — *why*: `--strict-mcp-config` stops a planted worktree `.mcp.json` from adding servers.
4. Extend `_REJECTED_OPTIONS` — *why*: the launcher owns the flag.
5. Update `test_prepare_shell_prefix_writes_policy_and_launcher` (it writes the config in the worktree today) and add the new tests.

### `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'def prepare_shell_prefix(cwd: Path, settings: dict, mode: str, *, rtk: bool) -> dict[str, str]:')
# BEFORE — insert above `def prepare_shell_prefix(` (verified: packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:1007)
def prefix_mcp_config(cwd: Path) -> Path | None:
    """Return the primary checkout's MCP configuration when it declares at least one server.

    Args:
        cwd: A path inside the linked worker worktree.

    Returns:
        ``<primary>/.mcp.json``, or ``None`` when it is absent, malformed or declares no server.
    """
    path = _native_roots(cwd)[2] / ".mcp.json"
    servers = _load_json(path).get("mcpServers")
    return path if path.is_file() and isinstance(servers, dict) and servers else None
```
```python
# occurrences: 1 (verified: grep -cF 'mcp_argv=tuple(tuple(argv) for argv in _prefix_mcp_argv(cwd / ".mcp.json")),')
# REPLACE that line (verified: packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:1043); compute `mcp_config = prefix_mcp_config(cwd)` before `policy = PrefixPolicy(`
        mcp_argv=tuple(tuple(argv) for argv in (_prefix_mcp_argv(mcp_config) if mcp_config else [])),
```
```python
# occurrences: 1 (verified: grep -cF 'command = [claude, "--agent", "sdd-worker"]')
# AFTER — insert below that line (verified: packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:1189); `uses_prefix` is set where prepare_shell_prefix is called (line 1183)
    if uses_prefix:
        # FILL IN: append ["--mcp-config", str(path), "--strict-mcp-config"] or ["--strict-mcp-config"] + warning
        #          — bounded by spec §2 M1 (variadic --mcp-config must be followed directly by --strict-mcp-config)
```
**Why**: the policy and the session must read the same file, and it must be one the session cannot write.

### `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` / `packages/ai-parrot/tests/sdd/test_sdd_launch.py` (MODIFY)
```python
# FILL IN: tests listed under Test Specification — bounded by AC 1–3 of the spec
```

### FILL IN checklist
- [ ] `launch_worker` flag emission and warning text
- [ ] the four tests

---

## Acceptance Criteria

- [ ] Policy `mcp_argv` lists the primary's stdio servers when the worktree has no `.mcp.json`.
- [ ] A `.mcp.json` in the worktree never contributes to `mcp_argv`.
- [ ] Legacy command contains `--mcp-config <primary>/.mcp.json` immediately followed by `--strict-mcp-config`.
- [ ] No primary config: `--strict-mcp-config` alone and a `WARNING` on stderr.
- [ ] A caller passing `--strict-mcp-config` gets exit 2.
- [ ] `ruff check` is clean on the changed files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_sdd_launch.py -q`

---

## Test Specification

```python
def test_prepare_shell_prefix_reads_primary_mcp_config(linked, monkeypatch, tmp_path): ...
def test_prepare_shell_prefix_ignores_worktree_mcp_config(linked, monkeypatch, tmp_path): ...
def test_launch_worker_legacy_passes_primary_mcp_config(tmp_path, monkeypatch): ...
def test_launch_worker_legacy_warns_without_mcp_config(tmp_path, monkeypatch, capsys): ...
```

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug scripts-native-claude-sandbox-fixes --feature-id FEAT-881`).
2. Check every `Depends-on` task is `done` in `sdd/tasks/index/scripts-native-claude-sandbox-fixes.json`.
3. Verify the Codebase Contract, mark the task `in-progress`, implement from the blueprint.
4. Run the Validation Commands, commit only the listed files.
5. Close with `parrot sdd task close TASK-5542 scripts-native-claude-sandbox-fixes verified`, fill the Completion Note, commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Code host session (/sdd-fix agent:sdd-fix:b338296a)
**Date**: 2026-11-12
**Notes**: Added prefix_mcp_config(); prepare_shell_prefix builds mcp_argv from the primary .mcp.json only; launch_worker emits --mcp-config <primary> --strict-mcp-config (or --strict-mcp-config alone with a stderr warning); --strict-mcp-config added to _REJECTED_OPTIONS. 186 tests pass in the two suites.

**Deviations from spec**: none
