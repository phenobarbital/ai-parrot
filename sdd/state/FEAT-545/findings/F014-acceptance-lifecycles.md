---
id: F014
query_id: Q016
type: grep
intent: Status lifecycles: brainstorm accepted / proposal accepted / spec approved
executed_at: 2026-09-10T01:00:00Z
duration_ms: 500
parent_id: null
depth: 0
---

# F014 — "Accepted" is a real state on both exploration docs; "approved" is the spec's gate

## Summary

Brainstorm: `**Status**: exploration | accepted | rejected` (template line 13; /sdd-brainstorm sets `exploration` at line 169). Proposal: `status: discussion | review | accepted`, with `accepted` only on explicit user "accept" (sdd-proposal.md 379-381). Spec: `draft | review | approved` (spec.md:14) and `/sdd-task` refuses non-approved specs (sdd-task.md:11). So "the accepted proposal definition" the source wants to hand to Codex is well-defined: a brainstorm or proposal whose status is `accepted` — the same document /sdd-spec §2 already treats as authoritative input. The brainstorm's Code Context section (template 154-200) is the verified-code payload that can travel in the brief.

## Citations

- path: `sdd/templates/brainstorm.md`
  lines: 13-14
  excerpt: |
    **Status**: exploration | accepted | rejected
    **Recommended Option**: <Option Letter>

- path: `.claude/commands/sdd-brainstorm.md`
  lines: 169
  excerpt: |
    3. Set `Status: exploration`.

- path: `.claude/commands/sdd-proposal.md`
  lines: 379-381
  excerpt: |
    - `status: discussion` if any unknowns remain unresolved
    - `status: review` if all unknowns resolved but user hasn't accepted
    - `status: accepted` only if the user explicitly says "accept" at the final summary

- path: `sdd/templates/spec.md`
  lines: 14
  excerpt: |
    **Status**: draft | review | approved

- path: `sdd/templates/brainstorm.md`
  lines: 154-200
  symbol: Code Context
  excerpt: |
    ## Code Context
    ### User-Provided Code
    ### Verified Codebase References  (#### Classes & Signatures / #### Verified Imports / #### Key Attributes & Constants)
    ### Does NOT Exist (Anti-Hallucination)

- path: `sdd/templates/brainstorm.md`
  lines: 102-142
  symbol: Recommendation / Feature Description / Capabilities / Impact & Integration
