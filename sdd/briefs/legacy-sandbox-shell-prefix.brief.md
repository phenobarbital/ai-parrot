---
kind: brief
slug: legacy-sandbox-shell-prefix
key: legacy-sandbox-shell-prefix
base_branch: dev
source:
  type: text
  ref: "operator report 2026-11-09: FEAT-860 sdd-worker in sandbox=legacy refused on every Bash call under auto mode"
  url: null
jira_issue_key: null
ledger_issue: null
created: "2026-11-09"
---

# Brief: Apply the SDD sandbox and RTK through `CLAUDE_CODE_SHELL_PREFIX` instead of rewriting Bash input

<!-- FEAT-698. One brief = one fix. Task files live in sdd/briefs/<slug>/tasks/. -->

## Problem

The FEAT-860 `sdd-worker` was launched with `sandbox=legacy` (`PARROT_SDD_SANDBOX_MODE=legacy`, hence
`PARROT_SDD_SANDBOX_BACKEND=bubblewrap`), Claude Code 2.1.319, in permission mode `auto`. Every Bash call was
refused once:

> The server-side auto mode classifier gave no verdict for Bash: a hook changed this call's input after auto
> mode reviewed it, so the review does not cover what would run.

Each call passed on a verbatim resend of a ~5.6 KB `/usr/bin/bwrap …` command. After three such calls the
worker stopped and asked the operator, calling the retries "workable but slow". Legacy mode is the fallback
for hosts where the Claude native sandbox is unavailable (for example, no AppArmor profile that lets `bwrap`
create user namespaces), so it has to work well there. Native mode has the same problem in a smaller form:
the measured replay in `sdd/state/BRIEF-sdd-native-sandbox-default/automode-rewrites.md` left 41 of 65
commands rewritten, all by RTK.

## Root cause

Auto mode classifies a Bash call before PreToolUse hooks run. The guard hook
(`parrot sdd worktree guard --hook` → `hook_response`,
`packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:979`) returns `updatedInput` whenever its
output differs from the input (`worktree_environment.py:1014`). In the `bubblewrap` backend, `_wrap_bash`
always returns `shlex.join(protected_argv(cwd, shell))` (`worktree_environment.py:711`), so every command
changes and every call is refused once. In every backend `_wrap_bash` also applies `rtk_rewrite`
(`worktree_environment.py:677`), so any command RTK optimises is refused once too. The fix is to apply both
transformations below the classifier: `CLAUDE_CODE_SHELL_PREFIX` runs a wrapper around each command after
auto mode has reviewed it, so the hook can stop changing the input.

## Research findings

- **Prefix semantics, measured live on Claude Code 2.1.321** (throwaway `claude -p` runs in the session
  scratchpad, haiku, `--setting-sources local`):
  - The prefix receives exactly **one argument**: the full command string.
  - It wraps the **Bash tool command**, every **hook command** (the hook string exactly as configured, e.g.
    `echo hook-ran >&2; exit 0`) and every **stdio MCP server** (`/bin/sleep 2` for
    `{"command": "/bin/sleep", "args": ["2"]}`).
  - The Bash string is Claude's preamble around the user command:
    `source <snapshot> 2>/dev/null || true && { shopt -u extglob || … } … && eval '<command, single-quoted,
    with '"'"' escapes>' < /dev/null && pwd -P >| /tmp/claude-<id>-cwd`. A Bash call's string therefore never
    equals a bare hook or MCP command.
  - Claude Code's "cannot vouch for that wrapper" warning applies only to hooks forwarded to cloud sessions;
    a local prefix ran without it.
- **Permission mode (side question).** `.claude/agents/sdd-worker.md` declares
  `permissionMode: bypassPermissions`, but a session started with `claude --agent <name>` does not apply it.
  A probe agent with that frontmatter recorded `permissionMode: default` in `-p` mode, with or without user
  settings. The interactive FEAT-860 session used the account default, `auto`. The frontmatter still applies
  when the agent runs as a subagent.
- **Launcher.** `native_claude_sandbox.launch_worker` (`native_claude_sandbox.py:903`) sets
  `PARROT_SDD_SANDBOX_BACKEND` from `launch_backend(mode)` (`:942`, `:491`), allocates
  `PARROT_SDD_CACHE_DIR` under `/tmp/claude-<uid>` (`:978`), and execs
  `claude --agent sdd-worker --setting-sources project,local --settings <json>` (`:1009`–`:1014`). The
  dev-loop dispatcher sets the backend the same way (`dispatchers/claude.py:662`).
- **Writable roots.** In legacy mode `protected_argv` (`worktree_environment.py:299`) mounts `/` read-only
  and binds `/tmp/claude-<uid>`, the worktree root, `.git`, `.parrot/ledger` and the sdd-coder evidence
  store writable. Claude's Write/Edit tools are limited to the worktree by `validate_write_path`
  (`worktree_environment.py:96`). Anything the prefix trusts (its script and policy) must live outside all of
  those, so not under `PARROT_SDD_CACHE_DIR`.
- **Prior art.** Brief `sdd-native-sandbox-default` (task 4) moved session-fixed variables into the launcher
  env and measured the remaining rewrites by deterministic transcript replay. Brief
  `sdd-sandbox-user-hook-isolation` keeps the user setting source (RTK's global hook) out of sandboxed
  sessions. Neither touched legacy mode.
- **Ledger.** No open issues on `worktree_environment.py` or `native_claude_sandbox.py`.

## Decisions

1. **Hooks and MCP servers keep today's behaviour (Q&A):** the launcher writes an exact allowlist of the
   hook and MCP launch commands it knows; the prefix passes only those through unwrapped and wraps
   everything else. A Bash call can never match, because it carries Claude's preamble.
2. **RTK moves into the prefix too (Q&A):** the prefix extracts the `eval '…'` payload, applies `rtk rewrite`
   and re-quotes it. RTK is an optimisation, not a boundary: an unrecognised preamble runs unchanged, and
   `bwrap` never depends on parsing it.
3. **The legacy guidance note moves into this brief (Q&A):** the last task writes the definitive text in the
   worker prompts.
4. **Permission mode is documented, not changed (Q&A):** the launcher keeps auto mode's review; the
   frontmatter finding goes into the wiki page.

Settled by research, not asked:

- The prefix proves it is in effect by exporting a marker to the processes it passes through (the guard
  hook among them). The hook skips the `bwrap` wrap or the RTK rewrite only when that marker matches the
  launch policy; otherwise it behaves exactly as today (fail closed).
- The prefix script and its policy live under `$XDG_STATE_HOME/parrot-sdd/shell-prefix/<session>/`
  (default `~/.local/state/…`), mode 0700/0500/0400, outside every writable root.
- If `bwrap` fails to start, the prefix exits non-zero. It never retries without the sandbox.
- The dev-loop dispatcher's seats are out of scope: they do not run under auto mode.

## Fix plan

- **HOTFIX-legacy-sandbox-shell-prefix-1** — `shell_prefix.py`: the prefix runtime (policy model,
  pass-through by exact match, `bwrap` wrap in legacy, marker export, fail-closed errors).
- **HOTFIX-legacy-sandbox-shell-prefix-2** — launcher wiring for legacy mode plus the hook's skip of the
  `bwrap` rewrite when the marker is valid. Depends on 1.
- **HOTFIX-legacy-sandbox-shell-prefix-3** — RTK inside the prefix for both modes, and the hook's skip of
  its own RTK rewrite. Includes a live check of whether and where the prefix runs under the native sandbox.
  Depends on 2.
- **HOTFIX-legacy-sandbox-shell-prefix-4** — live qualification, before/after measurement, worker prompt
  note, wiki page. Depends on 3.

## Validation commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_shell_prefix.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_sdd_launch.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -q`
