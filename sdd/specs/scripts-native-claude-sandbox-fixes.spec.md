---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [sdd-tooling, sandbox, shell-prefix, mcp, bugfix]
docs:
  policy: required
  pages:
    - wiki/sdd-tooling/dev_loop/claude-native-sandbox.md
---

# Feature Specification: Legacy shell-prefix fixes — MCP policy source, prefix runtime location, hook policy validation

**Feature ID**: FEAT-881
**Date**: 2026-11-12
**Author**: Jesus Lara
**Status**: approved
**Target version**: next patch
**Source**: `/sdd-fix` ledger group `fixgroup:97101219e16b` — `issue:975e2aa0bfb4` (vulnerability, major),
`issue:1f3a8f42fbc6` (bug, minor), `issue:93ac744f0a74` (tech_debt, minor)

---

## 1. Motivation

`parrot sdd launch worker <FEAT> --sandbox legacy` runs every shell invocation of the session through
`CLAUDE_CODE_SHELL_PREFIX`. The prefix (`shell_prefix.py`) wraps everything in Bubblewrap except the exact hook
commands and stdio-MCP argv recorded in an immutable session policy. Three defects sit on that path:

1. **`issue:1f3a8f42fbc6`** — `prepare_shell_prefix` reads the MCP allowlist from `<worktree>/.mcp.json`
   (`native_claude_sandbox.py:1043`). `.mcp.json` is gitignored, so a fresh worktree has none: `mcp_argv` is empty,
   nothing warns, and every MCP server is launched inside `bwrap`, where `parrot-sdd-coder` and `wikitoolkit` fail.
   The operator must hand-copy the primary `.mcp.json` into the worktree. That copy also makes the unsandboxed
   allowlist come from a file the worker can write.
2. **`issue:975e2aa0bfb4`** — the launcher stub execs `shell_prefix.py` from `Path(__file__)`'s directory. When the
   launcher runs from a feature worktree (`PYTHONPATH=<worktree>/packages/ai-parrot/src`), `shell_prefix.py` and
   `worktree_environment.py` are inside a writable root; a sandboxed Bash call can edit them and the next call
   runs the edited code unsandboxed.
3. **`issue:93ac744f0a74`** — the hook accepts a prefix policy on `sha256(file) == token` alone; the token is
   exported to MCP servers too; the launcher has no Claude Code version gate, expires live sessions after 7 days,
   over-collects `command:` lines from the agent frontmatter, and leaves an inherited prefix in the environment.
   Policy-validation tests are missing.

### Goals
- A legacy session loads and passes through exactly the MCP servers of the **primary** checkout's `.mcp.json`,
  with no file copied into the worktree.
- Everything the prefix executes unsandboxed lives outside every session-writable root.
- The hook trusts a prefix policy only after full validation; the token reaches hooks only.

### Non-Goals
- Changing native (`required`/`preferred`) sessions: they do not use the prefix (`_NATIVE_PREFIX_RTK_QUALIFIED = False`).
- Moving the hook-command allowlist sources (`<worktree>/.claude/settings*.json`, the agent file) to the primary.
- Network isolation in legacy mode.

---

## 2. Design

All paths below are under `packages/ai-parrot/src/parrot/sdd/scripts/`.

### M1 — MCP servers come from the primary checkout (`native_claude_sandbox.py`) — `issue:1f3a8f42fbc6`
- New `prefix_mcp_config(cwd: Path) -> Path | None`: returns `<primary>/.mcp.json` (primary =
  `_native_roots(cwd)[2]`) when it is a regular file whose `mcpServers` is a non-empty object; otherwise `None`.
- `prepare_shell_prefix` builds `mcp_argv` from `prefix_mcp_config(cwd)` (empty when `None`), never from
  `cwd / ".mcp.json"`.
- `launch_worker`, only in the branch that calls `prepare_shell_prefix`: append
  `--mcp-config <path> --strict-mcp-config` when a path is returned, and `--strict-mcp-config` alone plus a
  `launch_worker: WARNING … no MCP servers` line on stderr when it is `None`. `--strict-mcp-config` makes Claude
  Code ignore any `.mcp.json` in the worktree, so loaded servers and the policy always match.
- `--mcp-config` is variadic in the CLI: the launcher must emit `--mcp-config <path>` immediately followed by
  `--strict-mcp-config`, before `--settings`, so no forwarded argument or prompt is consumed as a config.
- Callers still may not pass `--mcp-config` (`_REJECTED_OPTIONS` unchanged); add `--strict-mcp-config` to it.

### M2 — Prefix runtime runs from the session directory (`native_claude_sandbox.py`) — `issue:975e2aa0bfb4`
- `prepare_shell_prefix` copies `shell_prefix.py` and `worktree_environment.py` (siblings of `__file__`) into the
  session directory with mode `0400`, and the `prefix` stub execs `<session>/shell_prefix.py` instead of the
  source-tree file. Script mode already resolves `worktree_environment` from the script's own directory.
- The existing check that the state root is outside `_prefix_writable_roots(cwd)` keeps the copies read-only to
  the session.

### M3 — Hook validates the policy; token is hook-only (`worktree_environment.py`, `shell_prefix.py`) — `issue:93ac744f0a74` (1), (3), (4)
- `_shell_prefix_policy()` loads the policy through `shell_prefix.load_policy` (symlink, permission and schema
  checks), compares the returned digest with the token, and returns a `PrefixPolicy | None`. It also returns
  `None` when `PARROT_SDD_SANDBOX_ROOTS` is set and its first entry differs from `policy.worktree`. Any
  `OSError`/`ValueError` yields `None` (the hook then wraps in `bwrap`, as today for a missing token).
- `shell_prefix` is imported lazily inside `_shell_prefix_policy`, package-relative or as a script sibling; in
  script mode pre-seed `sys.modules["worktree_environment"]` exactly as `_load_native_sandbox` does.
- `_wrap_bash` reads `policy.rtk` / `policy.mode` attributes instead of `dict.get`.
- `prepare_shell_prefix` records `worktree` as `_native_roots(cwd)[0]` so it equals the frozen root.
- `shell_prefix.main` sets `PARROT_SDD_SHELL_PREFIX_TOKEN` only when the argument is in `policy.hook_commands`;
  MCP pass-through commands run without it.

### M4 — Launcher hardening (`native_claude_sandbox.py`) — `issue:93ac744f0a74` (2), (5), (6), (7)
- **Version gate**: `MIN_PREFIX_CLAUDE_VERSION = (2, 1, 321)`. Before `prepare_shell_prefix`, run
  `claude --version` (10 s timeout); when the version is lower or cannot be parsed, print
  `launch_worker: shell prefix unavailable (…)` and return 1.
- **Session expiry**: `prepare_shell_prefix` writes `owner.pid` (the launcher pid, which `execvpe` hands to
  Claude) in the session directory; `_remove_expired_prefix_sessions` never removes a directory whose
  `owner.pid` names a live process (`_process_is_alive`).
- **Agent hooks**: `_agent_hook_commands` collects `command:` values only inside the frontmatter's top-level
  `hooks:` block (from the `hooks:` line to the next non-indented key).
- **Inherited prefix**: when the session does not prepare a prefix, `launch_worker` removes
  `CLAUDE_CODE_SHELL_PREFIX`, `PARROT_SDD_SHELL_PREFIX_POLICY` and `PARROT_SDD_SHELL_PREFIX_TOKEN` from the child
  environment; the token is removed in every mode.

### M5 — Test gaps and documentation — `issue:93ac744f0a74` (8)
- `test_shell_prefix.py`: symlinked policy, invalid JSON, non-object JSON, unknown key, wrong field type.
- `test_shell_prefix_live.py`: assert a positive write inside the worktree, so a model refusal cannot pass the
  test vacuously, and that the MCP process receives no token.
- `wiki/sdd-tooling/dev_loop/claude-native-sandbox.md`: MCP source of truth, runtime copy, version assumption,
  hook-only token, session expiry.

---

## 3. Acceptance Criteria

- [ ] With no `.mcp.json` in the worktree and one in the primary, the policy's `mcp_argv` lists the primary's
      stdio servers and the Claude command contains `--mcp-config <primary>/.mcp.json --strict-mcp-config`.
- [ ] With no `.mcp.json` in the primary, the launch prints a warning and passes `--strict-mcp-config` alone.
- [ ] A `.mcp.json` planted in the worktree never contributes to `mcp_argv`.
- [ ] The `prefix` stub execs a `0400` copy of `shell_prefix.py` inside the session directory; the copy runs a
      pass-through command with the source tree absent from `sys.path`.
- [ ] The hook ignores a token whose policy fails `load_policy` (bad schema, group-writable, symlink) or whose
      `worktree` differs from the frozen root, and wraps in `bwrap`.
- [ ] MCP pass-through commands receive no `PARROT_SDD_SHELL_PREFIX_TOKEN`; hook commands do.
- [ ] A legacy launch with Claude Code below 2.1.321, or an unparseable version, exits 1 before `exec`.
- [ ] A session directory older than 7 days with a live `owner.pid` survives cleanup.
- [ ] A `command:` line outside the agent's `hooks:` block is not allowlisted.
- [ ] A non-prefix launch does not forward an inherited `CLAUDE_CODE_SHELL_PREFIX`.
- [ ] The wiki page documents the new behaviour (`parrot sdd techwiki check`).

### Validation Contract

tests:
- packages/ai-parrot/tests/sdd/test_shell_prefix.py
- packages/ai-parrot/tests/sdd/test_sdd_launch.py
- packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py
- packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py
markers: none

### Out of the contract

`test_shell_prefix_live.py` starts a real Claude session, so it is not a gate.

---

## 4. Codebase Contract

Verified against `c1aa2e9cc8`.

| File | Symbol | Line |
|---|---|---|
| `native_claude_sandbox.py` | `_native_roots(cwd) -> (root, git_dir, primary)` | 147 |
| `native_claude_sandbox.py` | `_REJECTED_OPTIONS` | 691 |
| `native_claude_sandbox.py` | `_process_is_alive(pid)` | 875 |
| `native_claude_sandbox.py` | `_prefix_writable_roots(cwd)` | 920 |
| `native_claude_sandbox.py` | `_agent_hook_commands(path)` | 957 |
| `native_claude_sandbox.py` | `_prefix_mcp_argv(path)` | 973 |
| `native_claude_sandbox.py` | `_remove_expired_prefix_sessions(state_root)` | 988 |
| `native_claude_sandbox.py` | `prepare_shell_prefix(cwd, settings, mode, *, rtk)` | 1007 |
| `native_claude_sandbox.py` | `launch_worker(argv, *, cwd, initial_prompt, base_env)` | 1077 |
| `shell_prefix.py` | `load_policy(path) -> (PrefixPolicy, digest)` | 67 |
| `shell_prefix.py` | `decide(arg, policy, cwd)` | 132 |
| `shell_prefix.py` | `main(argv)` | 193 |
| `worktree_environment.py` | `_load_native_sandbox()` | 604 |
| `worktree_environment.py` | `_shell_prefix_policy()` | 652 |
| `worktree_environment.py` | `_wrap_bash(...)` — uses the policy at 695–696 and 714 | 668 |

Both `native_claude_sandbox.py` and `worktree_environment.py` are standard-library only and also run as scripts
(`if __package__: … else: …` import pairs); new code must keep both properties.

**Does NOT exist**: a Claude Code version check anywhere in the launcher; an `owner.pid` in prefix session
directories (only `_allocate_session_cache` writes one, for the cache); any read of the primary `.mcp.json`.

---

## 5. Risks

- `--strict-mcp-config` drops every MCP source other than the primary `.mcp.json` in legacy sessions. Sandboxed
  sessions already exclude the `user` setting source, so the project file is the only source in use.
- Tests in `test_worktree_environment.py` (≈ lines 940–1010) build minimal policies that `load_policy` rejects;
  M3 must rewrite them with complete, `0600` policies.
- These files are the sandbox's own policy: implement from a host session, not from a sandboxed `sdd-worker`.

---

## 6. Design Research Cross-Check

Status: skipped (ledger-driven fix lane; the source is three verified ledger issues, not an exploration doc).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-12 | Jesus Lara | Initial spec from `fixgroup:97101219e16b` |
