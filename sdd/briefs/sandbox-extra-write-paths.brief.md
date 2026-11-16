---
kind: brief
slug: sandbox-extra-write-paths
key: sandbox-extra-write-paths
base_branch: dev
source:
  type: text
  ref: "parrot CLI cannot run inside the sdd-worker/sdd-coder sandbox: navconfig cannot write /tmp/navigator/log"
  url: null
jira_issue_key: null
ledger_issue: null
created: '2026-11-16'
---

# Brief: Operator-declared extra writable paths for the SDD sandbox

<!-- FEAT-698. One brief = one fix. Task files live in sdd/briefs/<slug>/tasks/. -->

## Problem

Source (verbatim): "in sdd-coder and sdd-worker running in a isolated worktree, - The parrot CLI can't run
inside the worker sandbox because navconfig can't write /tmp/navigator/log., how to add writing on /tmp as a
possibility on sandbox (native and legacy)".

Every `parrot …` command imports navconfig, whose rotating file handler opens `/tmp/navigator/log/`. Inside a
native-sandboxed worker that path is read-only, so the CLI a worker needs (`parrot sdd task close`,
`parrot sdd tests select`, …) fails.

## Root cause

`native_sandbox_settings` compiles `filesystem.allowWrite` from a fixed list — the worktree, the common Git
directory, Claude's scratch root, and the worktree-admin / ledger / evidence directories
(`packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:429`). `etc/navigator.ini:25` sets
`logdir: /tmp/navigator/log/` with `filehandler_enabled: true`, and `/tmp/navigator` is not in that list. There
is no way for the repository operator to declare an additional writable directory.

The legacy Bubblewrap backend is not broken: `protected_argv` mounts a private `--tmpfs /tmp`
(`packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:342`), so the directory is creatable
there (verified with a `bwrap` run using the same mounts). It is, however, discarded with each command, so
those logs never reach the host.

## Research findings

- An environment override is not available: `logdir=<path>` in the environment did not change navconfig's
  resolved `logdir` (the ini value won), so the fix belongs in the sandbox policy.
- Opening all of `/tmp` in the native backend is rejected: there `/tmp` is the real host directory (other
  sessions' files, sockets, files host processes read back).
- Trusted configuration already exists: `[tool.parrot.sdd]` in the **primary checkout's** `pyproject.toml`,
  read by `load_launch_config` (`native_claude_sandbox.py:728`). The primary checkout is read-only for a
  worktree session in both backends, so a worker cannot widen its own policy.
- `worktree_environment.py` is standard-library only and runs under `python -S`; `tomllib` is available.
  Its directory helpers (`shared_ledger_dirs`, `coder_evidence_dirs`) take `(root, git_dir)`, return `()` for
  the primary checkout, and never raise, because `protected_argv` wraps every Bash call.
- Blast radius: `native_sandbox_settings` ← `plan_native_launch`, `validate_native_write_path`,
  `launch_worker`, `ClaudeCodeDispatcher._resolve_run_options`; `protected_argv` ← the hook and the shell
  prefix. No signature changes are needed.
- Ledger context for the two files: one unrelated open minor issue (`issue:32af43882efd`).

## Assumptions

- Base branch is `dev`, not the text-source default `main`: this is SDD tooling, and `main` lags these two
  files by about 250 lines (no shell-prefix code), so a `main`-based fix would not apply to the code in use.
- Anything inside the user's home directory is refused as an extra path. The use case is a log directory
  under `/tmp`; a home path would need a much finer deny list (`~/.ssh`, `~/.claude`, `~/.config`, …).
- When the session runs in the primary checkout itself (legacy hook), the key is ignored: there the session
  can edit `pyproject.toml`, so the value is not trusted, and `/tmp` is already a writable tmpfs.

## Fix plan

- `HOTFIX-sandbox-extra-write-paths-1`: add the `sandbox_extra_write_paths` key (validated, read from the
  primary checkout only), feed it to the native `allowWrite`, the legacy `--bind` list and
  `_prefix_writable_roots`, refuse a malformed value at launch, set `["/tmp/navigator"]` in this repository,
  document it, and test it — including that `/tmp` itself can never be granted.

## Validation commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`
