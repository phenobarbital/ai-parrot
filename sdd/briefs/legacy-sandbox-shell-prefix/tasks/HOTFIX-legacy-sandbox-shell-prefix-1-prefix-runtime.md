# HOTFIX-legacy-sandbox-shell-prefix-1: `shell_prefix.py`, the `CLAUDE_CODE_SHELL_PREFIX` runtime

**Feature**: legacy-sandbox-shell-prefix — apply the SDD sandbox and RTK through `CLAUDE_CODE_SHELL_PREFIX`
**Spec**: `sdd/briefs/legacy-sandbox-shell-prefix.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Claude Code runs `CLAUDE_CODE_SHELL_PREFIX <one argument>` for every Bash command, hook command and stdio MCP
server (brief, Research findings, measured on 2.1.321). This task writes the program behind that prefix. It
decides, per invocation, whether to pass the command through unchanged (a known hook or MCP launch command)
or to run it inside the legacy `bwrap` boundary. It does not touch the launcher or the hook (task 2) and does
not apply RTK (task 3).

## Scope

Create `packages/ai-parrot/src/parrot/sdd/scripts/shell_prefix.py`, runnable in script mode like
`worktree_environment.py` (sibling import of `worktree_environment`, no `import parrot`, stdlib only):

- `POLICY_ENV = "PARROT_SDD_SHELL_PREFIX_POLICY"` and `TOKEN_ENV = "PARROT_SDD_SHELL_PREFIX_TOKEN"`.
- `@dataclass(frozen=True) class PrefixPolicy`: `schema_version: int` (must be 1), `mode: str` (`"legacy"` or
  `"native"`), `worktree: str` (absolute), `hook_commands: tuple[str, ...]`, `mcp_argv: tuple[tuple[str, ...], ...]`,
  `rtk: bool`. `load_policy(path) -> tuple[PrefixPolicy, str]` returns the policy and the SHA-256 of the file
  bytes; it rejects unknown keys, wrong types, a relative `worktree`, a symlinked file, and a file writable by
  group or others.
- `decide(arg: str, policy: PrefixPolicy, cwd: Path) -> PrefixDecision` (frozen dataclass:
  `kind: Literal["passthrough", "wrap", "run"]`, `argv: list[str]`):
  - `arg` exactly equal to an entry of `hook_commands`, or `shlex.split(arg)` equal to an entry of
    `mcp_argv` → `passthrough`, `argv=["/bin/bash", "-c", arg]`.
  - otherwise, `mode == "legacy"` → `wrap`, `argv=protected_argv(cwd, ["/bin/bash", "-c", arg])`.
  - otherwise (`mode == "native"`) → `run`, `argv=["/bin/bash", "-c", arg]` (the native sandbox applies).
  - An `arg` that `shlex.split` cannot parse is never a pass-through.
- `main(argv) -> NoReturn`: exactly one argument, else fail. Read the policy from `POLICY_ENV`. `passthrough`
  execs with `TOKEN_ENV=<policy sha256>` added to the environment; `wrap` and `run` exec with `TOKEN_ENV`
  removed. On any error (argument count, missing or invalid policy, `bwrap` missing) print
  `sdd shell prefix: <reason>` to stderr and exit **2**: exit 2 makes a failed PreToolUse hook block the
  tool call instead of letting it proceed unguarded. Never fall back to running a command without the
  wrapper.
- Module docstring: why the prefix exists (auto mode reviews before hooks run), the one-argument contract,
  and the exit-2 rule.

Create `packages/ai-parrot/tests/sdd/test_shell_prefix.py` with the tests below.

**NOT in scope**: writing the policy or setting `CLAUDE_CODE_SHELL_PREFIX` (task 2); the hook's behaviour
(task 2); RTK (task 3); the dev-loop dispatcher's seats.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/shell_prefix.py` | CREATE | prefix runtime |
| `packages/ai-parrot/tests/sdd/test_shell_prefix.py` | CREATE | unit tests |

## Codebase Contract (Anti-Hallucination)

### Verified anchors (origin/dev @ 12a988cf3a, 2026-11-09)

- `worktree_environment.py:299` — `def protected_argv(cwd: Path, argv: Sequence[str], *, derive_pythonpath: bool = False) -> list[str]:`
- `worktree_environment.py:603` — `def _load_native_sandbox() -> Any:` (the script-mode sibling-import pattern to copy:
  `if __package__: from . import x` / `else: import x`)
- `worktree_environment.py:1029` — `def main(argv: Sequence[str] | None = None) -> None:` ("without importing application dependencies")

### Existing Signatures to Use

- `protected_argv(cwd, argv)` — the legacy filesystem boundary; it raises when `bwrap` is unavailable.

### Does NOT Exist

- `shell_prefix.py`, `PrefixPolicy`, `decide`, `POLICY_ENV`, `TOKEN_ENV`
- any use of `CLAUDE_CODE_SHELL_PREFIX` in the repository

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/shell_prefix.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/sdd/test_shell_prefix.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#protected_argv"
  ]
}
```

## Acceptance Criteria

- [ ] A configured hook command and a configured MCP argv pass through; the exec environment carries the
      policy token.
- [ ] A Bash preamble string (`source … && eval '<cmd>' < /dev/null && pwd -P >| …`) is wrapped in legacy
      mode and run unchanged in native mode, without the token.
- [ ] Zero or two arguments, a missing policy, an invalid policy and a group-writable policy file all exit 2
      with `sdd shell prefix:` on stderr and exec nothing.
- [ ] `import shell_prefix` in script mode does not import `parrot`.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_shell_prefix.py -q`

## Test Specification

`test_shell_prefix.py` (monkeypatch `os.execvpe`/`os.execve` to capture instead of exec):

- `test_hook_and_mcp_commands_pass_through_with_token`
- `test_bash_preamble_is_wrapped_in_legacy_mode`
- `test_bash_preamble_runs_unchanged_in_native_mode`
- `test_preamble_never_matches_allowlist` — a hook command embedded inside a preamble is wrapped.
- `test_errors_exit_2_and_exec_nothing` (parametrized over the failure cases above)
- `test_script_mode_does_not_import_parrot` (subprocess, `-E -s`)

## Agent Instructions

Read the brief first. Touch only the listed files. Stdlib only: the prefix runs before every command and
hook, so keep imports minimal.

## Completion Note

Implemented by seat gpt-5.6-terra (codex), 1 attempt, 321s, merged at a31814aeaa. Files: `shell_prefix.py`, `test_shell_prefix.py`. Merge-tier validation (background handle `d386f1d8-…:HOTFIX-1:merge`) finished green: 11 passed. Direct `pytest` in the sandbox fails on a navconfig `ErrorFileHandler` (log-dir write), so the engine validation was used instead.
