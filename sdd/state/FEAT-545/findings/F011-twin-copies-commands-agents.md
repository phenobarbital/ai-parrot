---
id: F011
query_id: Q020
type: glob
intent: Twin copies of the commands (.agent/workflows) and agents (_subagent_data) that must stay in sync
executed_at: 2026-09-10T01:00:00Z
duration_ms: 600
parent_id: F001
depth: 1
---

# F011 — Every sdd-* command has a twin in .agent/workflows/ (Antigravity), differing only by frontmatter

## Summary

`.agent/workflows/` holds a copy of each sdd-* command (added 41187b8e6, 2026-09-06, "infra for sdd-* in antigravity"). `sdd-spec.md` and `sdd-task.md` differ from their `.claude/commands/` originals by 6 diff lines each: a 4-line YAML `description` frontmatter and one reference line (`AGENTS.md` vs `CLAUDE.md`). Agents are likewise twinned into `parrot/flows/dev_loop/_subagent_data/` with byte-parity enforced by `tests/flows/dev_loop/test_subagent_parity.py`. Any edit to `/sdd-spec` or `/sdd-task` must be applied to both copies.

## Citations

- path: `.agent/workflows/sdd-spec.md`
  lines: 1-4
  symbol: frontmatter (only in twin)
  excerpt: |
    ---
    description: Scaffold a Feature Specification using SDD methodology, resolving flow types, reserving feature IDs, and carrying forward exploration context.
    ---

- path: `.agent/workflows/sdd-spec.md`
  lines: 426
  excerpt: |
    < - Worktree policy: `AGENTS.md` and `sdd/WORKFLOW.md`
    > - Worktree policy: `CLAUDE.md` (section "Worktree Policy")

- path: `.agent/workflows/sdd-task.md`
  lines: 1-296
  symbol: twin of .claude/commands/sdd-task.md (6 diff lines, frontmatter + reference line)

- path: `.agent/workflows/`
  lines: 0
  symbol: directory listing (sdd-* subset)
  excerpt: |
    sdd-brainstorm.md sdd-codereview.md sdd-done.md sdd-explain.md sdd-fromjira.md
    sdd-insight.md sdd-next.md sdd-proposal.md sdd-spec.md sdd-start.md sdd-status.md
    sdd-task.md sdd-tojira.md

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/`
  lines: 0
  excerpt: |
    sdd-autopilot.md sdd-codereview.md sdd-feedback.md sdd-planner.md sdd-qa.md
    sdd-research.md sdd-secondopinion.md sdd-worker.md

- path: `packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py`
  lines: 0
  symbol: parity test (exists)
