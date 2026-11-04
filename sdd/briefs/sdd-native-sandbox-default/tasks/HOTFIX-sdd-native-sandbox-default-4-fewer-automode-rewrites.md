# HOTFIX-sdd-native-sandbox-default-4: Fewer hook rewrites under auto mode, measured

**Feature**: sdd-native-sandbox-default — native sandbox by default, launcher-only guidance
**Spec**: `sdd/briefs/sdd-native-sandbox-default.brief.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: HOTFIX-sdd-native-sandbox-default-1
**Assigned-to**: unassigned

---

## Context

Auto mode classifies a Bash call **before** PreToolUse hooks run. When the hook sets
`updatedInput`, the call is refused once ("a hook changed this call's input after auto mode reviewed
it…") and the agent must resend the rewritten text verbatim. Measured on 2026-11-04: 14 of 34 Bash
calls in the legacy worker `22911c39`, and 28 of 74 in the native FEAT-793 worker `03ebac40`. Every
refusal costs an extra model turn plus the resent command (about 5 KB in legacy mode). Operator
decision: measure, then reduce. The timeout backstop, RTK and the scope guard may keep some rewrites
unavoidable; record which ones.

## Scope

1. **Baseline.** Write `sdd/state/BRIEF-sdd-native-sandbox-default/automode-rewrites.md`. Count, from
   the two transcripts above (or a fresh short launcher run), how many Bash calls were rewritten and
   why: env prefix, `timeout` backstop, RTK, scope guard. Use a small stdlib script, kept in the
   session scratchpad and not committed, that reads the JSONL and counts `tool_result` texts
   containing `auto mode classifier gave no verdict`.
2. **Move session-fixed variables into the launcher env.** In `native_claude_sandbox.launch_worker`
   (and the dev-loop dispatcher's sandboxed path, `dispatchers/claude.py:662`, so both stay
   consistent), export these once at launch: `UV_NO_SYNC`, `PYTHONDONTWRITEBYTECODE`, `XDG_CACHE_HOME`,
   `UV_CACHE_DIR`, and `PYTHONPATH` for the **session** worktree root. Then
   `native_command_environment` (or `_wrap_bash`) emits only the variables that differ from the
   inherited environment. In practice that is `PYTHONPATH` when the task cwd is a sub-worktree
   (`native_task_cwd`).
3. **Skip no-op rewrites.** When the env diff is empty and RTK and the guard leave the command
   unchanged, decide whether the `timeout` backstop can also come from somewhere other than a
   per-command rewrite. If the Bash tool's own `timeout` field already bounds the call, document why
   the backstop is still needed (`_backstop_seconds`, `command_timeout_seconds`) or drop it only for
   that case. Do not remove the backstop where it is the only bound. Any command that still needs a
   rewrite keeps today's behavior.
4. **After.** Repeat the measurement with a short launcher run on a scratch brief or feature, and
   record before and after numbers plus the list of remaining unavoidable rewrites in the same
   `automode-rewrites.md`.
5. **Guidance.** Add one line to the sdd-worker instructions (`.claude/agents/sdd-worker.md` and its
   `_assets/claude/agents/sdd-worker.md` twin, plus `.codex/agents/sdd-worker.toml` and its `_assets`
   twin if it carries the same Bash guidance). When auto mode reports that a hook changed the input,
   resend the hook's command once and verbatim, and never hand-write a `bwrap` or `env …` wrapper.

Tests (`test_worktree_environment.py`, `test_native_claude_sandbox.py`):

- The launcher env contains the moved variables. The dispatcher's sandboxed env does too.
- With an inherited env that already matches, the native wrapper omits those variables, and stays
  idempotent.
- A sub-worktree task cwd still gets its own `PYTHONPATH` (`native_task_cwd` path).
- The degraded banner and the task 1 fail-closed check are unaffected.

**NOT in scope**: changing Claude Code's auto-mode behavior; the legacy `bubblewrap` wrapper shape
(it must stay byte-identical, `test_legacy_hook_output_unchanged`).

### Operator notes (2026-11-04) — observed failure and two gaps to close

Observed: in a hand-launched worker (`claude --agent sdd-worker --setting-sources project,local`,
no launcher, so the legacy `bubblewrap` backend), the `code-reviewer` subagent got stuck. Its first
command was wrapped in `bwrap` with a 30-entry `PYTHONPATH` (~3 KB), and auto mode refused it as
expected. The subagent then resent the command *abbreviated*, with `PYTHONPATH` cut down to the core
`src` only. `_is_own_wrapper` correctly rejected that look-alike, the hook wrapped it again (`bwrap`
inside `bwrap`), auto mode refused it again, and the subagent could no longer run any Bash command
that needed classifier review. Evidence: session `22911c39-2d07-4b99-9a8a-525079d2f735`, subagent
`agent-ae6a9c0c2959fa373.jsonl` (Claude projects dir for the `gh-only-sandbox` worktree). Use it as a
third baseline transcript in step 1.

The lesson: in auto mode, every rewrite is a verbatim echo the model has to produce. Echo failures
grow with wrapper length and are worse in subagents. Reducing how often a rewrite happens is
necessary, but it is not enough; the length of the remaining rewrites matters too.

1. **Runtime-check wrapper for launches without the env var (task 1, decision 2).** With
   `PARROT_SDD_SANDBOX_BACKEND` unset, the hook still rewrites *every* command into the runtime-check
   wrapper, so every command that needs classifier review costs one refusal plus a verbatim resend.
   That is exactly how the session above was launched. In this task, measure that path as well, and
   keep its wrapper as short as possible. In particular, do not inline the full multi-package
   `PYTHONPATH` into the command text when it can be computed inside the wrapper at run time (for
   example, derived from the repo root instead of listed). Record its length before and after in
   `automode-rewrites.md`.
2. **Timeout backstop must not force a rewrite on every command (step 3).** If the `timeout -k`
   backstop is applied to every Bash call, the native backend keeps one rewrite per command and the
   auto-mode cost is only shortened, not removed. In native mode there is no Bubblewrap PID
   namespace to tear down, and that teardown was the reason for the backstop
   (`bounded_shell_argv` docstring). So either rely on the Bash tool's own `timeout` there and skip
   the backstop, or apply it only when the call carries an explicit `timeout` / `run_in_background`
   that the tool would not bound. Whichever you choose, justify it in `automode-rewrites.md`. The
   target: a plain native command with no env diff, no RTK change and no guard change goes through
   **unchanged** (no `updatedInput`). Add a test for that.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` | MODIFY | export session-fixed env at launch; env diff helper |
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` | MODIFY | emit only differing variables; no-op rewrite handling |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py` | MODIFY | same env on the dispatcher's sandboxed path |
| `.claude/agents/sdd-worker.md` | MODIFY | one-line resend guidance |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md` | MODIFY | twin |
| `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` | MODIFY | tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` | MODIFY | tests |
| `sdd/state/BRIEF-sdd-native-sandbox-default/automode-rewrites.md` | CREATE | before/after measurement |

---

## Codebase Contract (Anti-Hallucination)

### Verified anchors (origin/dev, 2026-11-04)
```
packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:520  def native_task_cwd(session_cwd: Path, command: str) -> Path:
packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:557  def native_command_environment(cwd: Path) -> dict[str, str]:
packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:807  def launch_worker(
packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:846      env[BACKEND_ENV] = launch_backend(mode)
packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:882      env[CACHE_DIR_ENV] = str(_allocate_session_cache())
packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:381   def _backstop_seconds(seconds: int) -> int:
packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:394   def command_timeout_seconds(tool_input: dict[str, Any]) -> int | None:
packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:432   def bounded_shell_argv(command: str, tool_input: dict[str, Any]) -> list[str]:
packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:528   def _wrap_bash(command: str, cwd: Path, tool_input: dict[str, Any], native: Any) -> str:
packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py:662      env[native_claude_sandbox.BACKEND_ENV] = native_claude_sandbox.launch_backend(mode)
```

### Facts verified in-session (2026-11-04)
- The native-sandbox command env already showed `XDG_CACHE_HOME` / `UV_CACHE_DIR` under
  `/tmp/claude-1000/parrot-sdd-cache/...` and the full worktree `PYTHONPATH`, all injected per command
  by the hook today.
- `native_command_environment` reads `CACHE_DIR_ENV` and the inherited `PYTHONPATH`. Moving the
  variables into the launcher env must not double-append `PYTHONPATH`.

### Does NOT Exist
- No env-diff helper exists today. Name it in `native_claude_sandbox.py` and keep it stdlib-only.

---

## Acceptance Criteria

- [ ] `automode-rewrites.md` records before and after counts and the remaining unavoidable rewrite
      reasons.
- [ ] A launcher session rewrites fewer Bash calls than the baseline, and no command loses its guard,
      RTK, timeout or sandbox.
- [ ] The legacy wrapper is byte-identical, and every backend stays idempotent.
- [ ] The sdd-worker instructions carry the one-line resend and no-hand-written-wrapper rule.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py -q`

## Agent Instructions

Read the brief first. Touch only the listed files. If a measurement run is impossible inside the
sandbox (no nested `claude`), record that in the Completion Note and measure from the transcripts
named above.

## Completion Note

Status `done-with-issues`. Operator decision (2026-11-04): the hook trusts the launcher's backend variable, so
task 1's fail-closed check on `claude-native` was **dropped**. `launch_worker` and the dispatcher now export the
session-fixed variables (`native_command_environment(cwd, environ)`, `PYTHONPATH` kept as a fixed point). In
`_wrap_bash`, `claude-native` emits only the env diff, keeps the `timeout` backstop only for an explicit
`timeout`/`run_in_background`, and returns an unchanged command as-is; `hook_response` then omits `updatedInput`.
`auto` is unchanged. Added the resend-verbatim line to both `sdd-worker.md` copies and rewrote the doc row.
Tests: 222 passed (worktree_environment, native_claude_sandbox, sdd_launch).

Not done: (1) a live launcher before/after measurement and re-reading the transcripts — `automode-rewrites.md`
holds the operator's baseline and a derived "after"; (2) shortening the `auto` wrapper's `PYTHONPATH` (still the full
list); (3) `.codex/agents/sdd-worker.toml` guidance line (not checked).
