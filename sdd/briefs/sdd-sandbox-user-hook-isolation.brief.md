---
kind: brief
slug: sdd-sandbox-user-hook-isolation
key: 6756c929a450
base_branch: dev
source:
  type: ledger
  ref: issue:6756c929a450
  url: null
jira_issue_key: null
ledger_issue: issue:6756c929a450
created: '2026-10-29'
---

# Brief: Keep user-level PreToolUse hooks out of sandboxed SDD sessions

<!-- FEAT-698. One brief = one fix. Task files live in sdd/briefs/sdd-sandbox-user-hook-isolation/tasks/. -->

## Problem

Ledger `issue:6756c929a450` (vulnerability, major, discovered from FEAT-549):

> In sandboxed SDD sessions, some Bash commands run without Bubblewrap. In the session measured for
> issue:fa2d5a89771e, RTK's global hook rewrote 92 commands; about 5 of them ran as RTK's rewrite
> (`rtk <cmd>`) with no `bwrap` wrapper, so outside the sandbox, with write access to the primary
> checkout, the shared `.venv` and the home directory.

The policy in `.claude/rules/worktree-management.md` §4 (Bubblewrap is mandatory, never an
unsandboxed retry) is therefore not guaranteed.

## Root cause

Two `PreToolUse` hooks return `updatedInput` for the same Bash call: the global RTK hook
(`~/.claude/settings.json`) and the SDD sandbox hook, which wraps the command in bwrap at
`packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:463`. Claude Code runs matching
hooks in parallel and defines a merge rule only for permission decisions, so which `updatedInput`
wins is undefined. The sandbox can only be guaranteed if no other source of Bash-rewriting hooks
is loaded — i.e. the **user** setting source must stay out of sandboxed sessions. Today it does not:

- **Dispatched seats.** `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py:649`
  maps an empty `profile.setting_sources` to `None`. With `None`, the claude-agent-sdk (0.2.168,
  `_internal/transport/subprocess_cli.py:729`) appends no `--setting-sources` flag, so the CLI uses its
  default and loads user settings (and user hooks). The profile field
  (`packages/ai-parrot/src/parrot/flows/dev_loop/models/claude.py:32`) also accepts `"user"` explicitly.
  The default `["project"]` is safe, but nothing enforces it for the sandboxed subagents
  (`sdd-worker`, `sdd-coder`, gated at `dispatchers/claude.py:621`), and no test proves it.
- **Interactive sessions.** `claude --agent sdd-worker` (documented at `CLAUDE.md:240`) loads all
  setting sources, so the global RTK hook and any plugin hooks (e.g. GitKraken's catch-all
  `PreToolUse`) run beside the agent-file hook (`.claude/agents/sdd-worker.md:27`,
  `.claude/agents/sdd-coder.md:16`). This is the main exposure path; native `sdd-coder` seats started
  with the Agent tool inherit the same session settings.

## Research findings

- `hook_response` (`worktree_environment.py:445`) is correct on its own; the bug is hook
  coexistence, not the wrapper.
- `ClaudeAgentRunOptions.setting_sources` is forwarded only when not `None`
  (`packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/claude_agent.py:442`).
- The dispatcher injects the sandbox hook via `extra_args["settings"]` (`--settings`, a flag source),
  which is independent of `--setting-sources`; excluding `user` does not drop it.
- Existing test `packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py:147` only asserts the
  default `["project"]`; nothing covers an empty list or an explicit `"user"`.
- `claude --help` lists `--setting-sources <sources>` (user, project, local).
- Related: PR #1858 (open, branch `fix-fa2d5a89771e-sandbox-hook-rtk-rewrite`) makes the sandbox hook
  apply `rtk rewrite` itself inside bwrap, so dropping the global RTK hook does not lose output
  compaction. It does not keep the global hook out. This brief does not depend on it, but interactive
  sessions lose RTK compaction until it merges.
- Ledger context: no other open issues on the touched files.

## Decisions

- Interactive lane: **docs + launcher** — update the documented launch commands to pass
  `--setting-sources project,local` and add `scripts/sdd/launch_worker.sh` that always does, plus a
  check that the agent-file hook still loads. Accepted cost: user-level permissions, plugins and
  `~/.claude/CLAUDE.md` are not loaded in those sessions.
- Native Claude Code sandbox (fix option 3): **include as a research task** — experiments and a
  written report only; no production change unless the experiment proves it safe.

## Fix plan

1. `HOTFIX-6756c929a450-1` — Dispatcher: for sandboxed subagents (`sdd-worker`, `sdd-coder`), always
   forward an explicit `setting_sources` list that never contains `"user"` and is never `None`; tests.
2. `HOTFIX-6756c929a450-2` — Interactive lane: `scripts/sdd/launch_worker.sh`, doc updates for every
   `claude --agent sdd-worker` launch line, and a test of the launcher's argv.
3. `HOTFIX-6756c929a450-3` — Research: native Claude Code sandbox as defense in depth; report under
   `sdd/state/6756c929a450/`, follow-up ledger issue if it is viable.

## Validation commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_models.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`
- `pytest tests/sdd/test_launch_worker.py -q`
