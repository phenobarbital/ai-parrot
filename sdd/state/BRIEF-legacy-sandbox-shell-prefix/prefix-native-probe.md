# Native shell-prefix probe

- Date: 2026-11-10
- Claude Code: 2.1.321
- Setup: a throwaway linked Git worktree, `claude -p --model haiku`, native settings produced by
  `native_sandbox_settings`, and `CLAUDE_CODE_SHELL_PREFIX` set to a logging wrapper.

The CLI started and emitted its connector warning, but produced no model output and never invoked the
logging prefix. Consequently there is no native argument shape, `SANDBOX_RUNTIME`, or `uid_map` observation
to parse. Native launches therefore remain without a shell prefix; legacy launches qualify the prefix with
RTK enabled. This is fail-closed for the optimisation: the native hook retains its existing RTK rewrite and
the native OS sandbox boundary does not depend on prefix parsing.
