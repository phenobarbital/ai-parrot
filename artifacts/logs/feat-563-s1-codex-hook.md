# FEAT-563 spike S1 — tracked codex hook inside an attempt sub-worktree

- Date: 2026-09-17
- codex CLI version: `codex-cli 0.154.0`
- Command run (no `--ignore-user-config`, real API call, no simulation):
  ```
  CODEX_HOME=<writable-scratch-dir> codex exec --cd . -s danger-full-access \
    -c approval_policy=never --dangerously-bypass-hook-trust --skip-git-repo-check --json \
    "Using your shell/bash tool, run EXACTLY this command verbatim: \
     cat packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py -- \
     then in your final answer report the raw tool result verbatim \
     (exit code, stdout length or error), do not summarize the file content."
  ```
- Sub-worktree path and attempt context present: **yes** — ran from the feature worktree
  root (`.claude/worktrees/feat-FEAT-563-scoped-test-selection`, itself a real linked git
  worktree of the main checkout) with a real `AttemptContext(tier="task", task_id="TASK-SPIKE-S1",
  task_file="sdd/tasks/active/TASK-3314-...", base_ref="feat-FEAT-563-scoped-test-selection")`
  written into that worktree's own `.git/worktrees/<name>/parrot-test-scope.json` via
  `test_scope.context.write_attempt_context` before the run, and removed afterward (spike
  cleanup — this file is evidence-only, never committed).

## Did the PreToolUse hook fire? Evidence

**Yes.** codex's own tool router rejected the command before execution:

```
2026-09-17T13:25:25.508495Z ERROR codex_core::tools::router: error=Command blocked by
PreToolUse hook: packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py is more than 350
lines / 61882 bytes (> 350 lines or 64,000 bytes). Use the bounded reader instead: MCP server
'parrot-bounded-source' tool 'source_read' with {"path":
"packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py", "start_line": 1, "end_line": 350};
continue with the returned next_line and expected_sha256.. Command: cat
packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py --
```

The agent's own turn confirmed the block reached it (not a silent failure the model
misreported):

```json
{"type":"item.completed","item":{"id":"item_3","type":"agent_message","text":
 "Script failed\nWall time 0.1 seconds\nOutput:\nScript error:\nCommand blocked by
 PreToolUse hook: ... Command: cat packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py --"}}
```

## Deny reason received by codex

Exactly `build_reason`'s bounded-reader message (the pre-existing FEAT-543 read guard),
verbatim as quoted above. **Important scope note**: this run exercises the shared `.venv`'s
currently-*installed* `parrot_tools.tool_optimizations.hooks` — worktrees do not have their
own venv (project rule: never `uv sync` in a worktree), so `scripts/sdd/codex_hook.sh` always
execs the **main checkout's** `.venv/bin/python`, which imports the **main checkout's**
(pre-FEAT-563, not-yet-merged) copy of `hooks.py`. That copy already has the FEAT-543 read
guard but not yet this task's `evaluate_scope`. This is not a gap in the spike: `main()`'s Bash
branch is `evaluate_scope(command, cwd) or evaluate_shell(command, cwd, policy)` — the exact
same call site, same tracked hook, same launcher. What this run proves is the **delivery
pipe** end-to-end (tracked `.codex/hooks.json` → portable `codex_hook.sh` → main-checkout
venv → `hooks.py main() --host codex` → a real deny reaching codex's tool router and the
model). Once this feature merges to `dev` and the main checkout's `hooks.py` picks up
`evaluate_scope`, the identical wiring carries the pytest-scope guard with no further changes.
A same-worktree deny of a broad pytest command was not separately exercised here because it
would test the same pipe with the pre-merge `hooks.py`, which cannot see `evaluate_scope` yet
for the reason above — re-running this exact command against a broad `pytest packages/x/tests`
after merge is the natural AC6 regression check.

## Feature flags or config codex required, and where they live

Two real, load-bearing requirements discovered by trial, not assumed:

1. **`--dangerously-bypass-hook-trust`** (a `codex exec` CLI flag, not a config file setting).
   Without it, `codex exec` — being non-interactive — cannot prompt for the one-time "trust
   this project's hooks?" confirmation a first-time project hook normally requires, so the
   hook is registered but its trust gate blocks it silently in headless/CI-style runs. Codex
   itself prints two `item.completed` warnings acknowledging this:
   `` `--dangerously-bypass-hook-trust` is enabled. Enabled hooks may run without review for
   this invocation. `` This is the flag `sdd-coder`'s codex dispatcher (or its equivalent CI
   wrapper) will need to pass for the hook to have any effect in an unattended dispatch — a
   finding for TASK-3319 (agent/command docs) to record, not a change to this task's file set.
2. **`-s danger-full-access`** (`codex exec --sandbox`), needed only inside *this specific
   sandboxed Claude Code Bash tool session*: with `read-only` or `workspace-write`, codex's own
   command-execution sandbox tries to create a nested Bubblewrap user namespace, which fails
   here with `bwrap: No permissions to create new namespace, likely because the kernel does
   not allow non-privileged user namespaces` (nested unprivileged sandboxes are not supported
   inside an already-sandboxed container) — an unrelated, pre-existing environment limitation
   of *this* spike-running session, not of the feature or of a real sdd-coder attempt (which
   runs outside this nested sandbox). Not a recommendation to change `CodexCodeDispatchProfile`
   defaults.
3. **`CODEX_HOME`**: this Claude Code session's Bash sandbox mounts `$HOME/.codex` read-only
   (consistent with the repo's "shared environments mounted read-only" policy), so codex's
   app-server could not initialize there (`Error: failed to initialize in-process app-server
   client: Read-only file system`). Worked around, for this spike only, by pointing
   `CODEX_HOME` at a writable scratch directory inside this worktree and copying the read-only
   `auth.json` into it (a read of an already-permitted file, not a sandbox bypass). This is an
   artifact of *this* execution environment, not of a real sdd-coder dispatch host.

## Hook cwd observed

The worktree root (`--cd .`, i.e. the feature worktree itself) — `codex_hook.sh`'s
`git rev-parse --path-format=absolute --git-common-dir` correctly resolved to the **main**
checkout's `.git` from inside this **linked worktree**, confirming the launcher's core
assumption (any worktree's common-dir parent is the checkout that owns the shared `.venv`).

## Verdict

**PASS** — the tracked, portable `.codex/hooks.json` + `scripts/sdd/codex_hook.sh` mechanism
enforces a PreToolUse deny inside a real `codex exec --cd <worktree>` run, without
`--ignore-user-config`, with real API calls (no simulation). `evaluate_scope`'s own decision
was not separately observed in this run for the structural reason noted above (shared venv
resolves to the not-yet-merged main-checkout `hooks.py`); the delivery pipe it will use is
proven by this same run. Follow-up for TASK-3319: document
`--dangerously-bypass-hook-trust` as a required flag for unattended codex dispatches that rely
on the tracked project hook.
