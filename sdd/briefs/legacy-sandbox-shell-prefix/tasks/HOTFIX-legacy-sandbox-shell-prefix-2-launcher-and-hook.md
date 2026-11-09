# HOTFIX-legacy-sandbox-shell-prefix-2: legacy launches set the prefix; the hook stops wrapping in `bwrap`

**Feature**: legacy-sandbox-shell-prefix — apply the SDD sandbox and RTK through `CLAUDE_CODE_SHELL_PREFIX`
**Spec**: `sdd/briefs/legacy-sandbox-shell-prefix.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: HOTFIX-legacy-sandbox-shell-prefix-1
**Assigned-to**: unassigned

---

## Context

Task 1 created the prefix runtime in `packages/ai-parrot/src/parrot/sdd/scripts/shell_prefix.py`. This task
turns it on for `sandbox=legacy` launches: the launcher writes the policy and points
`CLAUDE_CODE_SHELL_PREFIX` at it, and the guard hook stops returning a `bwrap` rewrite when it can prove the
prefix is in effect. A plain Bash command then reaches the shell exactly as auto mode reviewed it, so it is
not refused.

## Scope

In `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py`:

- `shell_prefix_state_root() -> Path`: `$XDG_STATE_HOME/parrot-sdd/shell-prefix` (default
  `~/.local/state/parrot-sdd/shell-prefix`).
- `prepare_shell_prefix(cwd: Path, settings: dict, mode: str, *, rtk: bool) -> dict[str, str]`:
  - Create `<state root>/<uuid4>/` with mode 0700. Refuse (`RuntimeError`) when it resolves under any root
    the session can write: the worktree, its `.git`, the primary checkout's worktree root and
    `.parrot/ledger`, the sdd-coder evidence store, and `/tmp/claude-<uid>`.
  - Collect `hook_commands` from every hook `command` in: `settings` (what the launcher passes with
    `--settings`, including the notification `Stop` hook), the worktree's `.claude/settings.json` and
    `.claude/settings.local.json`, and the `hooks:` frontmatter of the worktree's
    `.claude/agents/sdd-worker.md`. Collect `mcp_argv` as `[command, *args]` for every `mcpServers` entry of
    the worktree's `.mcp.json` with a `command`. Missing files contribute nothing.
  - Write `policy.json` (0400) in the `PrefixPolicy` shape with `schema_version=1`, `mode`, `worktree`,
    `rtk`. Write the executable `prefix` (0500): `#!/bin/sh` + `exec <sys.executable> -E -s <absolute path
    of shell_prefix.py> "$@"`.
  - Remove sibling session directories older than 7 days.
  - Return `{"CLAUDE_CODE_SHELL_PREFIX": <prefix path>, "PARROT_SDD_SHELL_PREFIX_POLICY": <policy path>}`.
- `launch_worker`: when `mode == "legacy"`, after `settings` is final (after the notification hook block,
  before building `command`), `env.update(prepare_shell_prefix(cwd, settings, mode, rtk=False))`. A
  `RuntimeError` prints `launch_worker: shell prefix unavailable (<reason>)` and returns 1: never launch
  legacy without it, because the hook would then fall back to per-command rewrites silently. Update the
  `mode=legacy` stderr notice to say Bash runs through the prefix's Bubblewrap.

In `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py`:

- `_shell_prefix_policy() -> dict | None`: the parsed policy when `PARROT_SDD_SHELL_PREFIX_TOKEN` equals the
  SHA-256 of the file at `PARROT_SDD_SHELL_PREFIX_POLICY`; `None` otherwise (unset, unreadable, mismatch).
  The prefix sets the token only on processes it passes through, so the model cannot forge it.
- `_wrap_bash`, backend `bubblewrap`: when the policy is valid and its `mode` is `"legacy"`, do not call
  `protected_argv`. Apply the same rule as the `claude-native` branch: return the command unchanged unless
  the scope guard or RTK changed it, or the call has an explicit `timeout`/`run_in_background` (then only
  `bounded_shell_argv`, no `bwrap`). With no valid policy, keep today's full `bwrap` wrap.
- `_is_own_wrapper`: the new output must be a fixed point (`hook(hook(x))` adds no `updatedInput`).
- `hook_response` docstring: describe the prefix case for `bubblewrap`.

Tests in `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py`,
`packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` and
`packages/ai-parrot/tests/sdd/test_sdd_launch.py`, listed below.

**NOT in scope**: RTK in the prefix and the native launch path (task 3); the dev-loop dispatcher
(`dispatchers/claude.py:662`); worker prompts and docs (task 4).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` | MODIFY | `prepare_shell_prefix`, legacy wiring |
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` | MODIFY | skip the `bwrap` rewrite under a valid prefix |
| `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` | MODIFY | policy and state-dir tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` | MODIFY | hook tests |
| `packages/ai-parrot/tests/sdd/test_sdd_launch.py` | MODIFY | legacy launch sets the prefix env |

## Codebase Contract (Anti-Hallucination)

### Verified anchors (origin/dev @ 12a988cf3a, 2026-11-09)

- `native_claude_sandbox.py:34` — `CACHE_DIR_ENV = "PARROT_SDD_CACHE_DIR"` ; `:35` — `ROOTS_ENV = "PARROT_SDD_SANDBOX_ROOTS"`
- `native_claude_sandbox.py:188` — `def native_root_env(cwd: Path) -> dict[str, str]:`
- `native_claude_sandbox.py:491` — `def launch_backend(mode: str) -> str:`
- `native_claude_sandbox.py:877` — `def _allocate_session_cache() -> Path:`
- `native_claude_sandbox.py:903` — `def launch_worker(` ; `:942` — `env[BACKEND_ENV] = launch_backend(mode)` ;
  `:944` — `if mode == "legacy":` ; `:978` — `env[CACHE_DIR_ENV] = str(_allocate_session_cache())` ;
  `:1009` — `command = [claude, "--agent", "sdd-worker"]` ; `:1014` — `command += ["--settings", json.dumps(settings), *forwarded]`
- `worktree_environment.py:54` — `def repository_paths(cwd: Path) -> tuple[Path, Path | None]:`
- `worktree_environment.py:96` — `def validate_write_path(cwd: Path, path: Path) -> None:`
- `worktree_environment.py:525` — `def bounded_shell_argv(command: str, tool_input: dict[str, Any]) -> list[str]:`
- `worktree_environment.py:651` — `def _wrap_bash(` ; `:711` — `return shlex.join(protected_argv(cwd, shell))`
- `worktree_environment.py:723` — `def _is_own_wrapper(` ; `:979` — `def hook_response(` ; `:1014` — `if wrapped != command:`

### Existing Signatures to Use

- `PrefixPolicy`, `load_policy`, `POLICY_ENV`, `TOKEN_ENV` (task 1, `shell_prefix.py`)
- the `claude-native` branch of `_wrap_bash` (`worktree_environment.py:682`–`693`) as the pattern for "rewrite
  only when something changed"

### Does NOT Exist

- `prepare_shell_prefix`, `shell_prefix_state_root`, `_shell_prefix_policy`
- any `CLAUDE_CODE_SHELL_PREFIX` handling in the launcher today

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_sdd_launch.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#launch_worker",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#launch_backend",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#_wrap_bash",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#_is_own_wrapper",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#hook_response",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#bounded_shell_argv"
  ]
}
```

## Acceptance Criteria

- [ ] A legacy `launch_worker` run (claude exec mocked) exports `CLAUDE_CODE_SHELL_PREFIX` and
      `PARROT_SDD_SHELL_PREFIX_POLICY`; the policy lists the launcher's hooks, the project hooks, the agent
      frontmatter hook and the `.mcp.json` servers; files have modes 0400/0500 in a 0700 directory.
- [ ] A state root under `/tmp/claude-<uid>` or the worktree is refused, and the launch returns 1.
- [ ] With a valid token, the `bubblewrap` hook returns no `updatedInput` for a plain command and never emits
      `bwrap`; with a missing or mismatched token it emits today's full `bwrap` wrap.
- [ ] `hook(hook(x))` is unchanged for both shapes.
- [ ] Native and `auto` launches are unchanged.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_sdd_launch.py -q`

## Test Specification

- `test_prepare_shell_prefix_writes_policy_and_launcher` (fake `HOME`/`XDG_STATE_HOME` under `tmp_path`)
- `test_prepare_shell_prefix_refuses_writable_root`
- `test_launch_worker_legacy_exports_shell_prefix` (`test_sdd_launch.py`)
- `test_bubblewrap_hook_skips_wrap_with_valid_prefix_token`
- `test_bubblewrap_hook_wraps_without_or_with_forged_token`
- `test_bubblewrap_prefix_output_is_fixed_point`

## Agent Instructions

Read the brief first. Touch only the listed files. Never write under the real `HOME` in tests. Keep the
fail-closed rule: no valid token means today's `bwrap` wrap.

## Completion Note

Pending; populated by the task finalizer after implementation and validation.
