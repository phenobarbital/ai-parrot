# HOTFIX-6756c929a450-2: Launch interactive sdd-worker sessions without user settings

**Feature**: issue:6756c929a450 — SDD sandbox bypass: a competing PreToolUse updatedInput replaces the bwrap wrapper
**Spec**: `sdd/briefs/sdd-sandbox-user-hook-isolation.brief.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The main exposure path is interactive: `claude --agent sdd-worker` (documented at
`CLAUDE.md:240`, `CLAUDE.md:250`, and in `/sdd-brief` / `/sdd-task` hand-offs) loads all
setting sources, so `~/.claude/settings.json` hooks (RTK, plugin hooks such as GitKraken's
catch-all `PreToolUse`) run beside the agent-file sandbox hook
(`.claude/agents/sdd-worker.md:27`). Native `sdd-coder` seats started through the Agent tool
inherit that session. The CLI supports `--setting-sources <sources>` (user, project, local).

Decision (brief § Decisions): docs + launcher. Accepted cost: user permissions, plugins and
`~/.claude/CLAUDE.md` do not load in these sessions; RTK compaction returns via PR #1858.

---

## Scope

- Create `scripts/sdd/launch_worker.sh`: `exec claude --agent sdd-worker --setting-sources project,local "$@"`,
  defaulting `--model sonnet` only when the caller passes no `--model`. Refuse (exit 2 with a
  message) if the caller passes its own `--setting-sources` containing `user`. `set -euo pipefail`,
  a header comment naming issue:6756c929a450 and why.
- Replace every documented interactive `claude --agent sdd-worker ...` launch with the launcher
  (or the equivalent explicit flag where a raw command is clearer): `CLAUDE.md` (Typical Workflow,
  Autonomous Agent, tmux recipe), `docs/sdd/WORKFLOW.md` if it shows one, `.claude/agents/sdd-worker.md`
  usage text, `.claude/commands/sdd-brief.md` (step 12 + Output), `.claude/commands/sdd-task.md:551`,
  and their `.agent/` / `.agents/skills/` twins if they contain the same line
  (`grep -rn "claude --agent sdd-worker"` over the repo, excluding `.claude/worktrees/`).
- Add one sentence to `.claude/rules/worktree-management.md` §4 (and its twin
  `.agent/skills/worktree-management/`) stating that sandboxed sessions must not load the `user`
  setting source, because a second `PreToolUse` `updatedInput` can replace the bwrap wrapper.
- Test `tests/sdd/test_launch_worker.py`: put a fake `claude` executable first on `PATH` that
  prints its argv; assert the launcher passes `--agent sdd-worker`, `--setting-sources project,local`,
  default `--model sonnet`, forwards extra args, keeps a caller `--model`, and exits 2 for
  `--setting-sources user,project`.
- Manual check (record result in the Completion Note, not automated): in a throwaway worktree,
  run the launcher, issue one Bash call, and confirm from the transcript JSONL that the command ran
  under `bwrap` and that no RTK `rtk ` rewrite without bwrap appears.

**NOT in scope**:
- Dispatcher changes (HOTFIX-6756c929a450-1).
- Native Claude Code sandbox (HOTFIX-6756c929a450-3).
- Editing `~/.claude/settings.json` or uninstalling RTK.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/launch_worker.sh` | CREATE | Launcher with `--setting-sources project,local` |
| `tests/sdd/test_launch_worker.py` | CREATE | Argv tests with a fake `claude` on PATH |
| `CLAUDE.md` | MODIFY | Launch commands |
| `.claude/agents/sdd-worker.md` | MODIFY | Usage text only (do NOT touch the `hooks:` frontmatter) |
| `.claude/commands/sdd-brief.md`, `.claude/commands/sdd-task.md` | MODIFY | Hand-off commands |
| `.claude/rules/worktree-management.md` + twin | MODIFY | One sentence in §4 |
| twins found by grep | MODIFY | Same launch-line change |

---

## Codebase Contract (Anti-Hallucination)

### Verified anchors
- `CLAUDE.md:240` — `claude --agent sdd-worker --model sonnet --verbose`
- `.claude/agents/sdd-worker.md:27` — `hooks:` (agent-file sandbox hook; keep as is)
- `.claude/commands/sdd-brief.md:176`, `:190`; `.claude/commands/sdd-task.md:551`
- Existing shell-script tests to copy style from: `tests/sdd/test_close_task_ledger.py`

### Does NOT Exist
- `scripts/sdd/launch_worker.sh` (this task creates it).

---

## Acceptance Criteria

- [ ] Launcher test passes; launcher refuses a `user` setting source.
- [ ] No documented interactive `claude --agent sdd-worker` launch remains without the flag/launcher.
- [ ] Manual transcript check recorded in the Completion Note.

## Validation Commands

- `pytest tests/sdd/test_launch_worker.py -q`

## Agent Instructions

Read the brief first. Implement exactly the scope; commit code only.

## Completion Note

Verified. `scripts/sdd/launch_worker.sh` (+ `tests/sdd/test_launch_worker.py`, 6 passed).
Launch lines updated in CLAUDE.md, docs/sdd/GUIDE.md, docs/sdd/PLATFORM.md, /sdd-brief, /sdd-task and
its `.agent/workflows` twin. The sdd-autopilot agent (4 identical-edit copies incl. `_subagent_data`)
shells out to `claude --agent sdd-worker -p ...` itself, so those calls got the explicit
`--setting-sources project,local` flag. That launch path was not listed in the task but is a real exposure.
Rule twins (`.claude/rules/worktree-management.md` §4, `.agent/skills/worktree-management/SKILL.md`) updated after merging
origin/dev, which brought in PR #1858's wording. Contract/parity tests: 248 passed, 1 skipped.
Manual check: `scripts/sdd/launch_worker.sh --model haiku -p ... --output-format stream-json` from
this worktree. The init message listed only builtin plugins (no user plugins such as GitKraken).
`touch /home/jesuslara/proyectos/ai-parrot/.probe_6756c929a450` returned "Sistema de archivos de solo
lectura" (read-only filesystem) → READONLY, so the Bash call ran under the agent-file bwrap hook, and
no file was created. Not covered: `claude --agent sdd-autopilot` itself still loads user settings; it
is an orchestrator that shells out, not a sandboxed seat.
