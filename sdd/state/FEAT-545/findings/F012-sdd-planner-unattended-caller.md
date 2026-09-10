---
id: F012
query_id: Q014
type: read
intent: sdd-planner: the unattended dev-loop caller of /sdd-spec
executed_at: 2026-09-10T01:00:00Z
duration_ms: 500
parent_id: null
depth: 0
---

# F012 — /sdd-spec is also run unattended by the sdd-planner subagent (Sonnet) inside the dev-loop

## Summary

`.claude/agents/sdd-planner.md` (model: sonnet, tools include SlashCommand) runs `/sdd-spec` then `/sdd-task` non-interactively from a brainstorm/proposal (lines 45-53) and must emit one PlannerOutput JSON; any non-zero step aborts the plan (93-99). Consequence: a new Codex phase inside `/sdd-spec` must (a) be non-blocking when the `codex` binary is absent or times out, and (b) never require a human gate when invoked from the planner — the same "no external reviewer → say so and continue" fallback as the review policy.

## Citations

- path: `.claude/agents/sdd-planner.md`
  lines: 23-26
  symbol: frontmatter
  excerpt: |
    model: sonnet
    permissionMode: default
    tools: Read, Grep, Glob, Bash, Write, SlashCommand

- path: `.claude/agents/sdd-planner.md`
  lines: 45-53
  symbol: steps 2-3
  excerpt: |
    2. **Generate the spec, if missing**. If `document_kind` is `"brainstorm"` or
       `"proposal"`, run `/sdd-spec` to scaffold and fill in `sdd/specs/<slug>.spec.md`
    3. **Decompose into tasks**. Run `/sdd-task <spec-path>`

- path: `.claude/agents/sdd-planner.md`
  lines: 93-99
  symbol: Failure handling
  excerpt: |
    If any step fails (`/sdd-spec` non-zero, `/sdd-task` non-zero, worktree
    collision), STOP and emit a final assistant turn explaining what failed
