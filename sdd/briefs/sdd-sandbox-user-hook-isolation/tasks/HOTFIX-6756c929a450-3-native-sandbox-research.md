# HOTFIX-6756c929a450-3: Research Claude Code's native sandbox as defense in depth

**Feature**: issue:6756c929a450 — SDD sandbox bypass: a competing PreToolUse updatedInput replaces the bwrap wrapper
**Spec**: `sdd/briefs/sdd-sandbox-user-hook-isolation.brief.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Tasks 1 and 2 keep competing user hooks out. As defense in depth, Claude Code's native
sandbox (`sandbox.enabled: true`, `sandbox.allowUnsandboxedCommands: false`, bubblewrap on
Linux, `sandbox.filesystem.allowWrite`) could enforce filesystem limits even if some hook
rewrote the command. Its interaction with hook-rewritten (`updatedInput`) commands and with
our own bwrap wrapper (nested bwrap) is undocumented. Decision: research only.

---

## Scope

- In a throwaway worktree, pass sandbox settings per session with `--settings '<json>'` and run
  experiments; record exact commands, settings JSON, `claude --version`, and observed results:
  1. Does a command rewritten by a `PreToolUse` `updatedInput` still run inside the native sandbox?
  2. Does our bwrap wrapper (`worktree_environment.py --hook`) work nested inside it, or fail?
  3. With `allowUnsandboxedCommands: false`, is there any retry path that runs unsandboxed?
  4. Can `allowWrite` express the worktree-management §4 policy (worktree + git metadata +
     `.claude/worktrees/` + `.parrot/ledger/` writable; primary checkout and `.venv` read-only)?
- Write the report to `sdd/state/6756c929a450/native-sandbox-research.md` with a verdict:
  adopt / adopt-with-limits / reject, and why.
- If the verdict is adopt or adopt-with-limits, open a follow-up ledger issue
  (`wikitoolkit ledger open --kind tech_debt --severity minor --discovered-from issue:6756c929a450 ...`)
  describing the production change. Do NOT make that change here.

**NOT in scope**:
- Any change to production code, agent files, or settings files.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/state/6756c929a450/native-sandbox-research.md` | CREATE | Experiment log + verdict |

---

## Codebase Contract (Anti-Hallucination)

### Verified anchors
- `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:445` — `def hook_response`
- `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:463` — `updatedInput` with the bwrap argv
- `.claude/rules/worktree-management.md` §4 — the filesystem policy to express

### Does NOT Exist
- No native-sandbox settings anywhere in the repo today.

---

## Acceptance Criteria

- [ ] Report exists with all four questions answered from observed runs (no unverified claims).
- [ ] Verdict stated; follow-up ledger issue opened if adoption is recommended.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`

## Agent Instructions

Experiments only. Never run anything that writes outside the throwaway worktree.

## Completion Note

Verified. Report: `sdd/state/6756c929a450/native-sandbox-research.md`. Verdict: adopt-with-limits.
A rewritten command stays inside the native sandbox, and the unsandboxed retry is refused.
Our bwrap cannot nest inside it (ENOSPC). On this host the sandbox needs `allowAllUnixSockets` because
AppArmor's userns restriction blocks the seccomp helper. Follow-up opened: issue:e57a19d91778.
