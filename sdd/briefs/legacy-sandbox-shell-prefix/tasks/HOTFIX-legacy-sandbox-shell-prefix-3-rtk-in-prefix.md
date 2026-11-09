# HOTFIX-legacy-sandbox-shell-prefix-3: RTK inside the prefix, for legacy and native launches

**Feature**: legacy-sandbox-shell-prefix — apply the SDD sandbox and RTK through `CLAUDE_CODE_SHELL_PREFIX`
**Spec**: `sdd/briefs/legacy-sandbox-shell-prefix.brief.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: HOTFIX-legacy-sandbox-shell-prefix-2
**Assigned-to**: unassigned

---

## Context

After task 2, the only per-command rewrites left are RTK's (`git status` → `rtk git status`), in both modes;
the measured native replay had 41 of 65 commands rewritten, all by RTK (brief, Problem). The operator chose to
move RTK into the prefix as well (brief, Decision 2). The prefix receives Claude's preamble with the user
command inside `eval '<single-quoted command>' < /dev/null` (brief, Research findings). RTK is an
optimisation: when the preamble is not recognised the command runs unchanged. The `bwrap` boundary never
depends on this parsing.

## Scope

1. **Native probe first.** With a throwaway `claude -p` run (haiku, a scratch git repo in the session
   scratchpad, the native sandbox settings `native_sandbox_settings` produces, `CLAUDE_CODE_SHELL_PREFIX`
   pointing at a logging script), record in `sdd/state/BRIEF-legacy-sandbox-shell-prefix/prefix-native-probe.md`:
   whether the prefix runs at all when the native sandbox is active, whether it runs inside or outside the
   sandbox (`SANDBOX_RUNTIME`, `/proc/self/uid_map`), and the exact argument shape. The CLI version goes in
   the file.

2. In `packages/ai-parrot/src/parrot/sdd/scripts/shell_prefix.py`:
   - `rtk_payload(arg: str) -> str`: find the single ` && eval ` segment followed by one shell word and
     ` < /dev/null`, parse that word with `shlex` (POSIX), call `worktree_environment.rtk_rewrite` on the
     command (it honours `PARROT_SANDBOX_RTK=0`), and when RTK changes it, rebuild the string with
     `shlex.quote`. Zero or several matches, a parse error, or no RTK change → return `arg` unchanged.
   - Apply it in `main` only to `wrap` and `run` decisions, and only when `policy.rtk` is true. Never to a
     pass-through. If the native probe shows a different argument shape for native sessions, support that
     shape too or leave native without prefix RTK, and say which in the probe file.

3. In `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py`, `_wrap_bash`: skip the
   `rtk_rewrite` call when `_shell_prefix_policy()` (task 2) is valid and its `rtk` is true. The scope guard
   still runs first and still sees the raw runner.

4. In `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py`, `launch_worker`: legacy launches
   pass `rtk=True` to `prepare_shell_prefix`. Native (non-degraded) launches also call
   `prepare_shell_prefix(cwd, settings, mode, rtk=True)` with policy `mode="native"`, **only if** the probe
   showed the prefix runs and its argument is parsed. Otherwise native launches stay as they are. A degraded
   launch never gets the prefix.

Tests in `packages/ai-parrot/tests/sdd/test_shell_prefix.py` and
`packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py`, listed below.

**NOT in scope**: the dev-loop dispatcher; changing what RTK rewrites; the live qualification and docs
(task 4).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/state/BRIEF-legacy-sandbox-shell-prefix/prefix-native-probe.md` | CREATE | probe findings |
| `packages/ai-parrot/src/parrot/sdd/scripts/shell_prefix.py` | MODIFY | `rtk_payload` |
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` | MODIFY | skip hook-side RTK under the prefix |
| `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` | MODIFY | `rtk=True`; native prefix if qualified |
| `packages/ai-parrot/tests/sdd/test_shell_prefix.py` | MODIFY | RTK payload tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` | MODIFY | hook skips RTK |

## Codebase Contract (Anti-Hallucination)

### Verified anchors (origin/dev @ 12a988cf3a, 2026-11-09)

- `worktree_environment.py:437` — `def _scope_guard(command: str, cwd: Path) -> tuple[str, str | None]:`
- `worktree_environment.py:560` — `RTK_ENV_SWITCH = "PARROT_SANDBOX_RTK"`
- `worktree_environment.py:564` — `def rtk_rewrite(command: str) -> str | None:`
- `worktree_environment.py:677` — `if optimized := rtk_rewrite(command):`
- `native_claude_sandbox.py:979` — `if mode != "legacy":` (native session env block in `launch_worker`)
- Preamble shape measured on Claude Code 2.1.321 (brief, Research findings):
  `… && eval 'git status --short && echo "it'"'"'s done"' < /dev/null && pwd -P >| /tmp/claude-3ba1-cwd`

### Existing Signatures to Use

- `prepare_shell_prefix`, `_shell_prefix_policy` (task 2); `decide`, `PrefixPolicy` (task 1, `packages/ai-parrot/src/parrot/sdd/scripts/shell_prefix.py`)
- `native_sandbox_settings` (`native_claude_sandbox.py`) for the probe's sandbox settings

### Does NOT Exist

- `rtk_payload`
- any knowledge in the repository of how the prefix behaves under the native sandbox (the probe produces it)

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "sdd/state/BRIEF-legacy-sandbox-shell-prefix/prefix-native-probe.md", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/shell_prefix.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_shell_prefix.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#rtk_rewrite",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#_scope_guard",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#_wrap_bash",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#launch_worker"
  ]
}
```

## Acceptance Criteria

- [ ] `rtk_payload` rewrites the `eval` payload and the result runs the same command under `bash -c`
      (round-trip test with quotes, `'"'"'` escapes, `$`, newlines and `&&`).
- [ ] An unrecognised string, two `eval` segments, or `PARROT_SANDBOX_RTK=0` leaves the argument byte-identical.
- [ ] Pass-through decisions are never RTK-rewritten.
- [ ] With a valid prefix policy whose `rtk` is true, the hook no longer emits RTK rewrites; the scope guard
      still blocks an over-broad pytest.
- [ ] The probe file records the CLI version and the native decision taken.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_shell_prefix.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`

## Test Specification

- `test_rtk_payload_round_trip` (parametrized commands; `rtk_rewrite` monkeypatched)
- `test_rtk_payload_leaves_unrecognised_input_unchanged`
- `test_rtk_payload_respects_switch_off`
- `test_passthrough_is_never_rtk_rewritten`
- `test_hook_skips_rtk_under_prefix_policy` / `test_scope_guard_still_blocks_under_prefix_policy`

## Agent Instructions

Read the brief first. Touch only the listed files. The probe runs `claude -p` once or twice with haiku in
the session scratchpad; keep its scripts there, uncommitted. RTK failures must never stop a command from
running, and must never affect the `bwrap` decision.

## Completion Note

Pending; populated by the task finalizer after implementation and validation.
