# TASK-4875 — Closeout hooks workflow twin updates

- **Feature**: fixgroup-5a875150e625
- **Feature ID**: FEAT-766
- **Spec**: sdd/specs/fixgroup-5a875150e625.spec.md
- **Status**: pending
- **Priority**: low
- **Estimated effort**: S
- **Depends-on**: TASK-4874
- **Assigned-to**: agent
- **Discovered-from**: `issue:1ac97711d2bd`

## Context

The three /sdd-done workflow twins need small updates to reflect the closeout
hooks subsystem introduced by FEAT-764.

## Scope

### In scope

1. Antigravity twin (`.agent/workflows/sdd-done.md`) — add a note before
   Step 10 explaining that `--resolve-jira` is now handled by the
   `jira.transition` builtin hook and Step 10 is retained only as a
   fallback reference for manual execution.

2. Codex twin (`.agents/skills/sdd-done/SKILL.md`) — document the
   `--finalize` exit-1 branch: when `--finalize` resolves pending agent
   hooks and the outcome has blocking failures, exit code is 1.

3. Both twins — document exit 3 (pending agents) handling: the caller
   should dispatch agent hooks listed in `pending_agents`, `--record` each
   result, then `--finalize` to resolve remaining pending hooks.

### NOT in scope

- Python code changes (TASK-4874).
- Changes to `.claude/commands/sdd-done.md` (the Claude twin's Step 10
  already documents the fallback).

## Files to Modify

- `.agent/workflows/sdd-done.md`
- `.agents/skills/sdd-done/SKILL.md`

## Codebase Contract

### Verified Content
- `.agent/workflows/sdd-done.md` Step 10 heading at line 623: `### 10. Transition Jira Ticket (if --resolve-jira)`
- `.agents/skills/sdd-done/SKILL.md` exists as a composite skill (directory with SKILL.md)

### Does NOT Exist
- Exit 3 documentation in `.agent/workflows/sdd-done.md`
- `--finalize` exit-code documentation in `.agents/skills/sdd-done/SKILL.md`

## Acceptance Criteria

- AC-1: `.agent/workflows/sdd-done.md` has a note before Step 10 about hook delegation.
- AC-2: `.agents/skills/sdd-done/SKILL.md` documents `--finalize` exit 1.
- AC-3: Both twins document exit 3 meaning and the record/finalize protocol.

## Validation Commands

```bash
grep -q "jira.transition" .agent/workflows/sdd-done.md
grep -q "finalize" .agents/skills/sdd-done/SKILL.md
grep -q "exit 3" .agent/workflows/sdd-done.md
```

## Completion Note

*(filled on close)*
