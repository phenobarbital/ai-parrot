# HOTFIX-sdd-native-sandbox-default-3: Every hand-off recommends `parrot sdd launch worker`

**Feature**: sdd-native-sandbox-default — native sandbox by default, launcher-only guidance
**Spec**: `sdd/briefs/sdd-native-sandbox-default.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: HOTFIX-sdd-native-sandbox-default-1, HOTFIX-sdd-native-sandbox-default-2
**Assigned-to**: unassigned

---

## Context

SDD commands, skills and agents tell operators to start a worker with
`claude --agent sdd-worker --setting-sources project,local …`. That is not a qualified native launch:
it gets no native sandbox, and today it falls back to the legacy `bwrap` wrapper. After tasks 1-2
the launcher can launch features **and** briefs, so every hand-off should name it. `CLAUDE.md` and
`docs/sdd/GUIDE.md` already do.

## Scope

Replace each direct worker launch with the launcher form: `parrot sdd launch worker <FEAT-ID|KEY>`
for interactive use, and `parrot sdd launch worker <FEAT-ID|KEY> --tmux [--detach]` for unattended or
background use. Keep twin pairs byte-identical (or identical apart from their existing intentional
difference), and keep `_assets/` copies in sync with their repository originals.

- `/sdd-brief`: `.claude/commands/sdd-brief.md:178,192` → `parrot sdd launch worker <KEY>`, plus the
  `_assets/claude/commands/sdd-brief.md` twin. The Codex skill `.agents/skills/sdd-brief/SKILL.md:42`
  and its `_assets/agents/skills/sdd-brief/SKILL.md` twin keep the in-Codex option and add the
  launcher as the sandboxed Claude option.
- `/sdd-task`: `.claude/commands/sdd-task.md:594`, `.agent/workflows/sdd-task.md:590`, and their
  `_assets/` twins.
- `sdd-autopilot`: `.claude/agents/sdd-autopilot.md` (277, 327, 362, 396, 720),
  `.agent/agents/sdd-autopilot/agent.md` and `.agents/agents/sdd-autopilot/agent.md`
  (284, 334, 369, 403, 725/727), and their `_assets/` twins. For non-interactive (`-p`) calls, check
  how `parrot sdd launch worker FEATURE [CLAUDE_ARGS]...` forwards Claude args (`launch_cli.py:27`);
  if `-p` cannot be forwarded cleanly, keep the call and add a one-line note that it is not natively
  sandboxed. Record which calls you kept in the Completion Note.
- `.claude/rules/worktree-management.md:55`, its twin `.agent/skills/worktree-management/SKILL.md:52`,
  and the `_assets/claude/rules/worktree-management.md` copy: replace "launch an interactive worker
  with `claude --agent sdd-worker --setting-sources project,local`" with the launcher. State the new
  backend rule in one sentence: unset backend = native when the native sandbox is active, otherwise
  the hook's Bubblewrap; `PARROT_SDD_SANDBOX_BACKEND=bubblewrap` forces legacy.
- `docs/dev_loop/claude-native-sandbox.md`: rewrite the paragraph at :32 ("A bare `claude --agent
  sdd-worker` is **not** a qualified native launch…") and the backend description to match task 1:
  - the three backends (`auto` default, `claude-native` fail-closed, explicit `bubblewrap`);
  - the runtime signals (`SANDBOX_RUNTIME`, `uid_map`);
  - the `bwrap` denial;
  - the fact that a nested `bwrap` inside the native sandbox can never work
    (`allowNestedUserNamespaces: false`);
  - the auto-mode refusal and verbatim resend.
- `sdd/specs/sdd-claude-native-sandbox.spec.md`: add a dated revision-history row (keep the table
  format), and amend the two statements "Missing metadata retains the existing Bubblewrap hook" and
  "Existing direct launches retain the legacy wrapper" with a pointer to this brief.
- `tests/sdd_scripts/test_sdd_brief_twin_contract.py:43,46`: update the pinned hand-off text.
- Leave `.claude/hooks/sdd-worker-format.sh:7` and `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py:12`
  unchanged: they describe process detection, not launch advice.

**NOT in scope**: code behavior (tasks 1, 2, 4). Historical SDD artifacts under `sdd/specs/` (except
the FEAT-768 revision row), `sdd/briefs/`, `sdd/state/`, `sdd/tasks/`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-brief.md` | MODIFY | launcher hand-off |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-brief.md` | MODIFY | twin |
| `.agents/skills/sdd-brief/SKILL.md` | MODIFY | add launcher option |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-brief/SKILL.md` | MODIFY | twin |
| `.claude/commands/sdd-task.md` | MODIFY | launcher hand-off |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-task.md` | MODIFY | twin |
| `.agent/workflows/sdd-task.md` | MODIFY | launcher hand-off |
| `packages/ai-parrot/src/parrot/sdd/_assets/agent/workflows/sdd-task.md` | MODIFY | twin |
| `.claude/agents/sdd-autopilot.md` | MODIFY | launcher calls |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-autopilot.md` | MODIFY | twin |
| `.agent/agents/sdd-autopilot/agent.md` | MODIFY | launcher calls |
| `.agents/agents/sdd-autopilot/agent.md` | MODIFY | launcher calls |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/agents/sdd-autopilot/agent.md` | MODIFY | twin |
| `.claude/rules/worktree-management.md` | MODIFY | launcher + backend rule |
| `.agent/skills/worktree-management/SKILL.md` | MODIFY | twin |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/rules/worktree-management.md` | MODIFY | asset copy |
| `docs/dev_loop/claude-native-sandbox.md` | MODIFY | backends, signals, auto mode |
| `sdd/specs/sdd-claude-native-sandbox.spec.md` | MODIFY | revision row + amended statements |
| `tests/sdd_scripts/test_sdd_brief_twin_contract.py` | MODIFY | pinned hand-off text |

---

## Codebase Contract (Anti-Hallucination)

### Verified anchors (origin/dev, 2026-11-04)
```
.claude/commands/sdd-brief.md:178        cd <wt> && claude --agent sdd-worker --setting-sources project,local --model sonnet --verbose
.claude/commands/sdd-brief.md:192        - Next step: `cd <wt> && claude --agent sdd-worker --setting-sources project,local --model sonnet --verbose`,
.claude/commands/sdd-task.md:594         # or, unattended:  claude --agent sdd-worker --setting-sources project,local --model sonnet --verbose
.agent/workflows/sdd-task.md:590         # or, unattended:  claude --agent sdd-worker ...
.claude/rules/worktree-management.md:55  - SDD in-process commands and native Claude Bash hooks use Bubblewrap filesystem protection. ...
.agents/skills/sdd-brief/SKILL.md:42     12. **Hand off**: ... open `<wt>` in Codex and ask: "Use the sdd-worker agent to implement <KEY>."
docs/dev_loop/claude-native-sandbox.md:32  A bare `claude --agent sdd-worker` is **not** a qualified native launch: ...
tests/sdd_scripts/test_sdd_brief_twin_contract.py:43  "```bash\ncd <wt> && claude --agent sdd-worker --setting-sources project,local --model sonnet --verbose\n```"
```

### Does NOT Exist
- `tests/sdd/test_no_repo_script_refs.py` forbids `parrot sdd run …` and `devloop launch-worker`
  spellings. Use only `parrot sdd launch worker`.
- A `.codex/agents/sdd-worker.toml` exists, but there is no Codex launcher. Codex hand-offs keep their
  in-Codex option.

---

## Acceptance Criteria

- [ ] No SDD command, skill, agent or rule (outside historical `sdd/` artifacts) recommends
      `claude --agent sdd-worker` as the way to start a worker, except autopilot `-p` calls kept with
      the documented note.
- [ ] Twin and `_assets` copies stay in sync (the installer/asset-sync tests pass).
- [ ] The sandbox doc and the FEAT-768 spec describe the new backend default.
- [ ] `test_sdd_brief_twin_contract.py` passes with the new hand-off text.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest tests/sdd_scripts/test_sdd_brief_twin_contract.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_installer.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py -q`

## Agent Instructions

Read the brief first. Text and instruction changes only. Before starting, rebase onto `origin/dev`
if `fix-sdd-worker-gh-only-sandbox-sdd-worker-gh-only-sandbox` has merged (it edits the
`_assets/claude/agents/` copies).

## Completion Note

Status `done-with-issues`. Replaced the direct worker launch with `parrot sdd launch worker …` in
`/sdd-brief`, `/sdd-task` (Claude + `.agent` twins), `sdd-autopilot` (all repo copies), both
`worktree-management` copies (plus the one-sentence backend rule), the Codex `sdd-brief` skill (launcher
added as the sandboxed Claude option), and the `_assets/` twins that exist. Rewrote the sandbox doc
(three backends, signals, `bwrap` denial, nested-bwrap impossibility, auto-mode resend), amended the two
FEAT-768 statements and added revision row 0.5, and updated the pinned text in
`test_sdd_brief_twin_contract.py`.

Kept (documented with a one-line "Not natively sandboxed" comment): the three autopilot `-p` calls
(`claude --agent sdd-worker … -p …`) per copy — the launcher starts an interactive `run <id>` session and
cannot forward `-p`.
No `_assets` twin exists for `.agent/agents/sdd-autopilot/agent.md` or `.agent/skills/worktree-management/SKILL.md`.

Validation: `test_sdd_brief_twin_contract.py` and `test_no_repo_script_refs.py` pass. `test_installer.py`:
6 failed / 76 passed — `test_untouched_file_upgrades_from_older_record` (extra upgrades of
`sdd-coder.md`/`sdd-worker.md`, which this task did not touch) and five `test_guard_hook_*` tests (the guard
hook line is baked with the shared `.venv/bin/parrot` path). I did not baseline them on `origin/dev`; they
look environmental/pre-existing but that is unverified.
The gh-only-sandbox branch (edits the `_assets/claude/agents/` worker/coder copies) was not rebased onto.

Resolved (2026-11-04, operator review): the 6 `test_installer.py` failures are pre-existing. The same 6 fail on
`origin/dev` (export of `origin/dev` + compiled modules: 6 failed / 60 passed). Cause: `_assets/claude/agents/`
`sdd-coder.md:21` and `sdd-worker.md:32` carry a guard hook baked to `/home/…/.venv/bin/parrot` on `dev` itself;
open PR #1951 fixes it. Not this branch's defect. The autopilot `-p` calls kept with a "Not natively sandboxed"
note are an accepted limitation (the launcher cannot forward `-p`). The gh-only-sandbox branch is still unmerged;
whichever PR merges second resolves the one-line `_assets` overlap. Status → `done`.
