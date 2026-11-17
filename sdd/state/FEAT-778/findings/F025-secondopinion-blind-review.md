---
id: F025
query_id: Q045
type: read
intent: "Blind adversarial review precedent (identity-marked, no primary reasoning) — sdd-secondopinion agent brief."
executed_at: 2026-10-30T16:46:28Z
duration_ms: 300
parent_id: null
depth: 0
merged_from: [FC-026-secondopinion-blind-review]
---

# F025 — `sdd-secondopinion` already codifies the "mutually blind, advisory, read-only contribution" protocol: neutral brief (diff + criteria + question), never the primary's reasoning, findings triaged CONFIRM/REJECT/ESCALATE

## Summary

`.claude/agents/sdd-secondopinion.md` (FEAT-375): read-only tools (Read, Grep, Glob, Bash), receives exactly three inputs, must not assume the primary agent's reasoning, never edits/commits/runs writes; every finding is later triaged by the primary as CONFIRM/REJECT/ESCALATE. This is the operational precedent for the `review` capability and for blind support contributions (minus the identity marker and the `contributions/<slug>.md` artifact).

## Citations

- path: `.claude/agents/sdd-secondopinion.md`
  lines: 1-30
  symbol: `frontmatter`
  excerpt: |
    name: sdd-secondopinion
    description: |  Adversarial second-opinion subagent ... Given a neutral brief — a diff, the linked requirements /
      ... It never receives the primary agent's reasoning or preferred conclusion
    tools: Read, Grep, Glob, Bash

- path: `.claude/agents/sdd-secondopinion.md`
  lines: 36-67
  symbol: `body rules`
  excerpt: |
    You receive a neutral brief consisting of exactly three things: ...
    You do NOT receive — and must never assume — the primary agent's reasoning, justification, or preferred conclusion.
    - **Advisory output only.** You never edit, write, or commit anything.
    - **NEVER execute tests or any command that writes.**

## Notes

CLAUDE.md "Adversarial Second Opinion" rules (never feed reasoning; verify evidence) are the governance text for this protocol.
