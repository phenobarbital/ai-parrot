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
settings, as FEAT-768 states.

## Still to do

A live before/after run (`parrot sdd launch worker <scratch brief>`, then count
`auto mode classifier gave no verdict` in its transcript) must be done on the host.
