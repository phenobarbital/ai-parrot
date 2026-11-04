# Auto-mode rewrites: before / after

Auto mode classifies a Bash call before PreToolUse hooks run. When the hook sets `updatedInput`, the call is
refused once and the agent must resend the hook's text verbatim (one extra turn plus the resent command).

## Baseline (operator measurement, 2026-11-04 — transcripts not re-read in this session)

| Session | Backend | Refused / Bash calls |
|---|---|---|
| `22911c39` (gh-only brief) | legacy `bubblewrap` | 14 / 34 |
| `03ebac40` (FEAT-793) | `claude-native` | 28 / 74 |

Why every call was rewritten (from the hook code): the `env UV_NO_SYNC=… PYTHONDONTWRITEBYTECODE=… PYTHONPATH=…
XDG_CACHE_HOME=… UV_CACHE_DIR=…` prefix on **every** command, plus the `timeout -k 5 <n>` backstop on every
command. RTK and the scope guard only change some commands. The legacy resend was ~5 KB (a 30-entry `PYTHONPATH`).

## After (derived from the hook logic — NOT a live launcher run)

`claude-native` (launcher session):

| Cause | Before | After |
|---|---|---|
| env prefix | always | launcher exports the five variables; emitted only when they differ from the inherited env (a sub-worktree task cwd gets its own `PYTHONPATH`) |
| `timeout` backstop | always | only with an explicit `timeout` or `run_in_background`; a plain call is bounded by the host |
| RTK / scope guard | when they change the command | unchanged |
| degraded banner | when degraded | unchanged |

So a plain command (no RTK change, no guard change, session-worktree cwd, no explicit timeout) is **not
rewritten**: no refusal, no resend. Remaining unavoidable rewrites: RTK-optimised commands, guard
rewrites/verdicts, sub-worktree `cd <task> && …`, explicit `timeout`/`run_in_background`, degraded launches.
Covered by `test_claude_native_*` in `test_worktree_environment.py`.

`auto` (backend unset, no launcher): every command is still rewritten into the runtime-branch wrapper because the
hook cannot know the session. Both branches now derive `PYTHONPATH` at run time
(`PYTHONPATH="$(printf '%s:' <root>/packages/*/src | sed 's/:$//')${PYTHONPATH:+:$PYTHONPATH}"`) instead of
listing every package `src`, so the resend no longer carries the ~3 KB literal (the `bwrap` branch drops its
`--setenv PYTHONPATH`; `bubblewrap` stays byte-identical). Covered by `test_auto_backend_derives_pythonpath_at_run_time`.

## Decision recorded

The task-1 fail-closed check on `claude-native` was dropped (operator, 2026-11-04): the hook trusts the launcher's
backend variable, which keeps plain commands rewrite-free. The enforcement boundary remains the native sandbox
settings, as FEAT-768 states. Follow-up (a7cec86e23): that trust now requires the launcher markers
(`PARROT_SDD_SANDBOX_ROOTS`, `PARROT_SDD_CACHE_DIR`); a hand-exported `claude-native` falls back to `auto`.

## Measured (2026-11-04, deterministic replay)

Auto mode refuses a Bash call exactly when the hook returns `updatedInput`, so the refusal count can be measured
without a model run: every **original** Bash command (verbatim resends of a hook rewrite skipped) from the three
baseline transcripts was replayed through the hook as a `PreToolUse` payload with `cwd` = this worktree.
"Before" = the hook on `dev` (main checkout code); "after" = this branch, with the exact environment
`launch_worker` exports (`native_root_env`, `PARROT_SDD_CACHE_DIR`, `PARROT_SDD_SANDBOX_BACKEND`,
`native_command_environment`). RTK was on (`rtk` on `PATH`) unless stated. Replay script kept out of the repo.

| Transcript (original commands) | before: legacy | before: native launcher | after: `auto` (no launcher) | after: native launcher | after: native launcher, RTK off |
|---|---|---|---|---|---|
| `22911c39` gh-only worker (20) | 20 / 5651 | 20 / 5001 | 20 / 2435 | **8 / 92** | 0 |
| `agent-ae6a9c0c…` code-reviewer subagent (5) | 5 / 5412 | 4 / 4747 | 4 / 1928 | **3 / 153** | 0 |
| `03ebac40` FEAT-793 worker (40) | 40 / 5437 | 40 / 4787 | 40 / 2007 | **30 / 204** | 0 |
| **Total (65)** | **65** | **64** | **64** | **41** | **0** |

Cells: rewritten commands / average resend length in characters (the one non-rewritten command in some columns
is a scope-guard denial, identical before and after).

Findings:

- With the launcher, rewrites drop from 64/65 to 41/65 and the text the model must echo shrinks from ~4.8 KB to
  ~150 characters. That shrinking is what fixes the code-reviewer failure in the operator notes: the abbreviated
  resend happened on a ~3 KB wrapper.
- **Every remaining rewrite is RTK's** (`git status` → `rtk git status`): with `PARROT_SANDBOX_RTK=0` the count is
  0/65. They are kept on purpose. A ~150-character echo costs one turn, while RTK's output compression saves far
  more on the command output, which is the token cost that dominates. Turning RTK off for workers is available
  (`PARROT_SANDBOX_RTK=0`) but not recommended.
- Without the launcher (`auto`), every command is still rewritten, as designed (the hook cannot see the session),
  but the resend is ~2 KB instead of ~5.4 KB because `PYTHONPATH` is derived at run time.
- Remaining unavoidable rewrites, by cause: RTK-optimised commands; scope-guard rewrites/verdicts; sub-worktree
  `cd <task> && …` (own `PYTHONPATH`); explicit `timeout`/`run_in_background`; degraded launches (banner); every
  `auto` command.

## Codex

The `.codex/agents/sdd-worker.toml` line is not applicable: Codex runs its own `PreToolUse` hook
(`.codex/hooks.json` → `scripts/sdd/codex_hook.sh`) inside its own `workspace-write` sandbox, and has no Claude
auto-mode classifier, so there is no refused-and-resent rewrite to guide.
