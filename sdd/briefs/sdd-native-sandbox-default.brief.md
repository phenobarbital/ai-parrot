---
kind: brief
slug: sdd-native-sandbox-default
key: sdd-native-sandbox-default
base_branch: dev
source:
  type: text
  ref: "operator report 2026-11-04: sdd-worker Bash fails with nested bwrap 'No permissions to create new namespace'"
  url: null
jira_issue_key: null
ledger_issue: null
created: "2026-11-04"
---

# Brief: Native sandbox by default for the SDD hook, launcher-only guidance

## Problem

An sdd-worker session showed (operator paste):

```
● Bash(/usr/bin/bwrap --die-with-parent --unshare-pid --new-session --ro-bind / / --proc /proc --dev /dev --tmpfs /tmp --bind /tmp/claude-1000 /tmp/claude-1000 --bind…)
  ⎿  Error: Exit code 1
     bwrap: No permissions to create new namespace, likely because the kernel does not allow non-privileged user namespaces.
● That failed because the nested bwrap can't create a namespace. I'll go back to the single-wrapped form that worked before.
```

Claude Code's native sandbox already runs every Bash command inside Bubblewrap. Wrapping again in
the hook's own `bwrap` is redundant and, under the native sandbox, fatal. Three related costs:

1. The hook treats a missing `PARROT_SDD_SANDBOX_BACKEND` as "legacy Bubblewrap", so every worker not
   started by `parrot sdd launch worker` silently runs the pre-FEAT-768 wrapper.
2. Every SDD command and skill that hands off to a worker recommends that unqualified direct launch
   (`claude --agent sdd-worker --setting-sources project,local`), and the launcher cannot launch a
   brief at all.
3. In auto mode every hook rewrite is refused once and resent verbatim, which nearly doubles Bash
   turns: 14 of 34 Bash calls in the legacy worker `22911c39` (gh-only brief), 28 of 74 in the native
   FEAT-793 worker `03ebac40`. The legacy resend carries a ~5 KB command each time.

## Root cause

`worktree_environment.main()` reads `PARROT_SDD_SANDBOX_BACKEND` and falls back to `"bubblewrap"`
when it is unset (`packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:637`,
`hook_response(..., backend=backend or "bubblewrap")`). That was a deliberate FEAT-768 decision
(`sdd/specs/sdd-claude-native-sandbox.spec.md`: "Missing metadata retains the existing Bubblewrap
hook"; "Existing direct launches retain the legacy wrapper"). The hook process runs **outside** the
sandbox, so it cannot tell whether the session it serves is natively sandboxed. When native settings
reach a session without the env var (hand-made `claude --settings …`, or any launch path that drops
it), `protected_argv` (`worktree_environment.py:229`) inserts `/usr/bin/bwrap` inside a sandbox
compiled with `"allowNestedUserNamespaces": False`
(`packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:427`), and every Bash call fails.
FEAT-768 never evaluated auto mode (zero mentions in the spec), so the per-rewrite refusal cost was
never measured. The launcher resolves only `sdd/tasks/index/*.json`
(`packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:104`), so `/sdd-brief`
(`.claude/commands/sdd-brief.md:178`) had no qualified launch to recommend.

## Research findings

Reproduced 2026-11-04 on the maintainer host (Claude Code 2.1.317/2.1.318, bwrap 0.9.0,
`kernel.apparmor_restrict_unprivileged_userns=1` with the bwrap AppArmor profile):

| Session | Hook backend | Result |
|---|---|---|
| bare host, `bwrap` inside `bwrap` | — | works (rc=0) |
| bare host, hook output re-wrapped (resend with changed `timeout`) | bubblewrap | double `bwrap`, still works |
| `claude -p --settings <native_sandbox_settings(wt)>`, no env var | bubblewrap (fallback) | **every Bash fails**: `No permissions to create new namespace` |
| same, `PARROT_SDD_SANDBOX_BACKEND=claude-native` | claude-native | works |

- **Detecting the native sandbox from inside the command.** Inside the native sandbox the command
  environment has `SANDBOX_RUNTIME=1` and `/proc/self/uid_map` is a single-uid map
  (`1000 1000 1`). A plain session has no `SANDBOX_RUNTIME` and `uid_map` is
  `0 0 4294967295`. Only the command can see this; the hook cannot.
- **Hook idempotency** (`_is_own_wrapper`, `worktree_environment.py:563`): a verbatim resend
  passes. Any edit to the command or a changed `timeout` field re-wraps it.
- **RTK is preserved.** `_wrap_bash` (`worktree_environment.py:528`) runs `rtk rewrite` on the inner
  command before wrapping (seen in transcripts: `bash -c 'rtk ls …; rtk read …'`). The global
  `rtk hook claude` is deliberately not loaded in sandboxed sessions (issue 6756c929a450).
- **Launcher env** (`native_claude_sandbox.launch_worker`, `:807`): sets `BACKEND_ENV`
  (`:846`), `ROOTS_ENV`, `CACHE_DIR_ENV`, `DEGRADED_ENV`. Modes `off` and degraded `preferred` set
  `PARROT_SDD_SANDBOX_DEGRADED=1` and run with **no** `sandbox` block on purpose (hook-only, banner).
- **`native_command_environment`** (`:557`) is what the native wrapper adds to each command:
  `UV_NO_SYNC`, `PYTHONDONTWRITEBYTECODE`, `PYTHONPATH` (per **task** cwd: sub-worktrees differ),
  `XDG_CACHE_HOME`, `UV_CACHE_DIR`. `bounded_shell_argv` adds a `timeout` backstop to every command.
- **Hook consumers:** `.claude/agents/sdd-worker.md:32` and `.claude/agents/sdd-coder.md:21`, both
  `parrot sdd worktree guard --hook` (`packages/ai-parrot/src/parrot/sdd/cli.py:241` →
  `worktree_environment.main`). The dev-loop dispatcher sets the env itself
  (`packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py:662`); in-process seats use
  `protected_argv` directly and are out of scope.
- **Direct-launch recommendations on `dev`:** `.claude/commands/sdd-brief.md:178,192`,
  `.claude/commands/sdd-task.md:594`, `.agent/workflows/sdd-task.md:590`,
  `.claude/agents/sdd-autopilot.md` (277, 327, 362, 396, 720), `.agent/agents/sdd-autopilot/agent.md`
  and `.agents/agents/sdd-autopilot/agent.md` (284, 334, 369, 403, 725/727),
  `.claude/rules/worktree-management.md:55` and twin `.agent/skills/worktree-management/SKILL.md:52`,
  plus every `packages/ai-parrot/src/parrot/sdd/_assets/` copy.
  `tests/sdd_scripts/test_sdd_brief_twin_contract.py:43,46` pins the old `/sdd-brief` hand-off text.
  `CLAUDE.md` and `docs/sdd/GUIDE.md` already recommend the launcher.
- **Ledger:** `wikitoolkit ledger context` on both sandbox modules returned no open issues.
- **Concurrent work:** `origin/fix-sdd-worker-gh-only-sandbox-sdd-worker-gh-only-sandbox` (unmerged,
  2 commits) touches only `_assets/claude/agents/sdd-coder.md` and `sdd-worker.md`; rebase before task 3.

## Decisions

1. **The default is native; legacy is an explicit opt-in** (operator, 2026-11-04).
   `PARROT_SDD_SANDBOX_BACKEND=bubblewrap` (or the launcher's `--sandbox legacy`) is the only way to get
   the unconditional Bubblewrap wrapper.
2. **No launcher, no native sandbox: fall back to Bubblewrap at runtime, never fail** (operator
   choice in Q&A). With the variable unset, the hook emits one wrapper that checks at run time:
   inside the native sandbox it runs the command directly (no nested `bwrap`); outside, it runs it
   through the legacy `bwrap` boundary. Nothing ever runs unsandboxed.
3. **With `PARROT_SDD_SANDBOX_BACKEND=claude-native` (launcher), the check fails closed.** If the
   command is not inside the native sandbox and `PARROT_SDD_SANDBOX_DEGRADED` is not `1`, it exits
   non-zero with a one-line message naming `parrot sdd launch worker <FEAT>`. Degraded and `off`
   launches keep today's banner behavior.
4. **A hand-written `bwrap` command is denied in native mode** (backend `claude-native`) with a
   one-line reason: the native sandbox is active; resend the command without the wrapper.
5. **All hand-offs recommend the launcher**, Claude and Codex variants alike, including `/sdd-brief`,
   which needs launcher support for brief keys.
6. **Auto-mode cost: measure and reduce** (operator choice). Move session-fixed variables into the
   launcher env, rewrite only when needed, and record which rewrites remain unavoidable (timeout
   backstop, RTK, scope guard).
7. This reverses the FEAT-768 statements quoted above. Task 3 amends
   `sdd/specs/sdd-claude-native-sandbox.spec.md` with a dated revision-history row.

## Assumptions

- The runtime check uses both signals: `SANDBOX_RUNTIME=1` **and**, on Linux, a single-line
  `uid_map` that does not start with `0 0 `. macOS (Seatbelt, uncertified) relies on
  `SANDBOX_RUNTIME` alone; the implementer verifies or documents that it is unverified.
- `parrot sdd launch worker <KEY>` resolves a brief by its slug, its key, or `BRIEF-<slug>`, from the
  brief worktree listed by `git worktree list`. Its initial prompt is `run <slug>`, matching how
  brief workers are started today.

## Fix plan

- **HOTFIX-sdd-native-sandbox-default-1:** hook backend default and the runtime branch (auto /
  native fail-closed / explicit legacy), the hand-written `bwrap` denial, and idempotency for the new
  wrapper shape, with tests.
- **HOTFIX-sdd-native-sandbox-default-2:** `parrot sdd launch worker` accepts brief keys, with tests.
- **HOTFIX-sdd-native-sandbox-default-3** (depends on 1 and 2): every hand-off recommends the
  launcher (all twins and `_assets`), the twin-contract test, `docs/dev_loop/claude-native-sandbox.md`,
  and the FEAT-768 spec revision.
- **HOTFIX-sdd-native-sandbox-default-4** (depends on 1): reduce rewrites under auto mode, and measure
  before and after.

## Validation commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_sdd_launch.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest tests/sdd_scripts/test_sdd_brief_twin_contract.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_installer.py -q`
