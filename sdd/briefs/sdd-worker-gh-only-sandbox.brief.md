---
kind: brief
slug: sdd-worker-gh-only-sandbox
key: sdd-worker-gh-only-sandbox
base_branch: dev
source:
  type: text
  ref: "operator request 2026-11-03 + live native-sandbox probe"
  url: null
jira_issue_key: null
ledger_issue: null
created: "2026-11-03"
---

# Brief: sdd-worker native sandbox — GitHub only through `gh`, config-driven allowed domains

## Problem

A real `parrot sdd launch worker` run ended with:

> Push blocked: git push failed because the sandbox doesn't allow github.com:22. The 7 closed
> tasks are only committed locally.

The operator wants the sandboxed sdd-worker to reach GitHub **only through the `gh` CLI**
(never raw `git` over SSH/HTTPS to `github.com`), without passing `--sandbox-allow-domain`
by hand on every launch. Consequence the operator explicitly wants documented: `/sdd-done`
(which pushes the branch) must run on the **host**, outside the sdd-worker session. Before
FEAT-633 `/sdd-done` was run from inside the sdd-worker; that no longer works.

## Root cause

The native sandbox compiled by `native_sandbox_settings()` has no egress unless domains are
passed explicitly: `"network": {"allowAllUnixSockets": False, "strictAllowlist": True,
"allowedDomains": domains}` (`packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:426`),
and the only source of `domains` is the launcher argv
(`native_claude_sandbox.py:745` → `plan_native_launch(cwd, allowed_domains=domains)` at `:755`;
CLI flag at `packages/ai-parrot/src/parrot/sdd/launch_cli.py:22`, forwarded at
`packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:410`). The remote is
`git@github.com:…` (SSH), which the sandbox proxy cannot carry at all
(`docs/dev_loop/claude-native-sandbox.md:137`: "Raw SSH is not supported in v1"). Separately,
`gh` stores its token in the desktop keyring (D-Bus, a Unix socket), which
`allowAllUnixSockets: False` blocks, so even with `api.github.com` allowed `gh` gets HTTP 401.
The worker instructions still tell the agent to `git push origin HEAD`
(`.claude/agents/sdd-worker.md:713`) and say `/sdd-done` "may run from inside this worktree"
(`.claude/agents/sdd-worker.md:752`).

## Research findings

Live probe (2026-11-03, CLI 2.1.317, `claude -p` with the exact settings from
`native_sandbox_settings()` and the env `launch_worker` sets — `PARROT_SDD_SANDBOX_BACKEND`,
`native_root_env()`, `PARROT_SDD_CACHE_DIR` — from a linked worktree):

| Config | `gh api user` | `gh pr list` | curl `github.com` | ssh :22 |
|---|---|---|---|---|
| no domains (today) | `host is not on the allow list` | ✗ | ✗ | DNS fails |
| `api.github.com` | HTTP 401 (keyring unreachable) | 401 | ✗ | DNS fails |
| `api.github.com` + `GH_TOKEN` in launch env | `phenobarbital` ✓ | ✓ | ✗ | DNS fails |

Gotcha found while probing: without the launcher env (`PARROT_SDD_SANDBOX_BACKEND=claude-native`)
the project hook wraps commands in its own bwrap, nested in the native sandbox, and fails with
`bwrap: No permissions to create new namespace`. Any manual reproduction must set that env.

- `launch_worker` is the single choke point for both launch paths: the direct path
  (`feature_launcher.launch` → `native_claude_sandbox.launch_worker`) and the tmux child
  (`feature_launcher.main --in-session` → `launch_worker`). Both run on the HOST before
  `execvpe(claude)`, so a token resolved there never crosses the sandbox boundary as argv.
- `_tmux_environment()` forwards only `PARROT_SDD_*`, `PATH`, `VIRTUAL_ENV` as `tmux -e NAME=VALUE`
  (visible in `ps`): the token must NOT go through it — resolve it in `launch_worker` instead.
- `resolve_sandbox_mode()` reads `[tool.parrot.sdd] sandbox` from the **worktree** pyproject and
  refuses `off`/`legacy` from there because the session can write that file. New keys widen the
  boundary, so they must be read from the **primary checkout** only (`_native_roots(cwd)[2]`).
- `native_claude_sandbox.py` is stdlib-only (imported as a script sibling by the hook; the tmux child
  runs with `python -S`): the config reader must use `tomllib` only.
- Twins: `.claude/agents/sdd-worker.md` ≡ `_assets/claude/agents/sdd-worker.md` except the hook
  command path; `.codex/agents/sdd-worker.toml` ≡ `_assets/codex/agents/sdd-worker.toml`;
  sdd-done lives in `.claude/commands/`, `.agents/skills/sdd-done/`, `.agent/workflows/` + their
  `_assets` twins.
- Tests: `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py`,
  `packages/ai-parrot/tests/sdd/test_sdd_launch.py`.

## Decisions

- GitHub egress from the sandbox is `api.github.com` only — `gh` works, `git push`/SSH/`github.com`
  stay blocked by design. (operator)
- Token source: `gh auth token` on the host (no dedicated PAT variable). If `GH_TOKEN` is already in
  the launch environment it is kept as is and `gh` is not called. (operator)
- `gh_token = true` but the token cannot be obtained (gh missing, not logged in, non-zero exit,
  timeout): print a WARNING (never the token, never gh's stdout) and launch without `GH_TOKEN`. (operator)
- `/sdd-done` runs on the host, never from inside the sdd-worker session; the worker commits, does
  not push, and tells the operator to run `/sdd-done` from the host. The launcher's existing
  host-side `prepare_upstream` keeps setting the upstream before launch. (operator)
- CLI opt-out `--no-gh-token` on `parrot sdd launch worker`, forwarded to the tmux child.

## Fix plan

1. **HOTFIX-sdd-worker-gh-only-sandbox-1** — `[tool.parrot.sdd] sandbox_allowed_domains` +
   `gh_token` read from the primary checkout's pyproject in `native_claude_sandbox.launch_worker`
   (union with `--sandbox-allow-domain`), `GH_TOKEN` injection via `gh auth token`, `--no-gh-token`
   flag through `launch_cli` / `feature_launcher` (both paths), repo pyproject set to
   `["api.github.com"]` + `gh_token = true`, tests.
2. **HOTFIX-sdd-worker-gh-only-sandbox-2** — documentation and agent instructions: gh-only policy,
   config keys, keyring/`GH_TOKEN` explanation, token scope warning, and "`/sdd-done` runs on the
   host" in the sandbox doc, sdd-worker (4 twins), sdd-done (6 twins), `CLAUDE.md`,
   `docs/sdd/WORKFLOW.md`.

## Validation commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_sdd_launch.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py -q`
