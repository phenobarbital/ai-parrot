---
id: F008
query_id: Q013
type: read
intent: sdd-secondopinion neutral-brief subagent (what a neutral brief is made of)
executed_at: 2026-09-10T01:00:00Z
duration_ms: 500
parent_id: null
depth: 0
---

# F008 — A "neutral brief" is exactly three things: artifact, requirements, question — never the primary's reasoning

## Summary

`.claude/agents/sdd-secondopinion.md` defines the neutral brief as *exactly* the diff, the acceptance criteria and a review question (lines 35-41), forbids receiving the primary agent's reasoning, requires specific/falsifiable findings (48-51), forbids writes and test execution in the read-only sandbox (56-67), and demands one JSON object matching a dispatcher-supplied schema (73-76). For a *design-research* seat the analogue is: artifact = accepted brainstorm/proposal (+ Code Context excerpts), requirements = constraints & goals, question = "how would you build this / what is missing / what would you do differently" — with Claude's draft spec explicitly withheld.

## Citations

- path: `.claude/agents/sdd-secondopinion.md`
  lines: 35-41
  symbol: brief definition
  excerpt: |
    You receive a neutral brief consisting of exactly three things: a
    **diff**, the **requirements / acceptance criteria** it is meant to satisfy,
    and a **review question**. You do NOT receive — and must never assume —
    the primary agent's reasoning, justification, or preferred conclusion.

- path: `.claude/agents/sdd-secondopinion.md`
  lines: 45-51
  symbol: Cardinal rules
  excerpt: |
    - **Advisory output only.** You never edit, write, or commit anything.
    - **Findings must be specific and falsifiable.** Every finding names a
      concrete file and line (when applicable)

- path: `.claude/agents/sdd-secondopinion.md`
  lines: 56-67
  symbol: read-only sandbox constraints
  excerpt: |
    - **NEVER execute tests or any command that writes.** Your sandbox is
      strictly read-only: NO path is writable — not the worktree, not even `/tmp`

- path: `.claude/agents/sdd-secondopinion.md`
  lines: 73-76
  symbol: One JSON object only
  excerpt: |
    Your final assistant turn must be exactly one JSON object ... conforming to the
    structured output schema the dispatcher appends to this brief
