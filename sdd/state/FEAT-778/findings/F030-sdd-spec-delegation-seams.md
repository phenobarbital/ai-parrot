---
id: F030
query_id: Q048
type: grep
intent: "Where sdd-spec / sdd-proposal already delegate to subagents (Agent calls) — the delegation seams for validate/write/review."
executed_at: 2026-10-30T16:46:28Z
duration_ms: 300
parent_id: null
depth: 0
merged_from: [FC-031-sdd-spec-delegation-seams]
---

# F030 — `/sdd-spec` lives at `.claude/commands/sdd-spec.md` (no `.claude/skills/sdd-spec/`); it contains no `subagent_type`/`Agent({` delegation today, unlike `/sdd-proposal` (research lanes + `sdd-contract-probe`)

## Summary

The planned path `.claude/skills/sdd-spec/SKILL.md` does not exist (ugrep: No such file). The command is `.claude/commands/sdd-spec.md`, and grepping it for `subagent_type`, `Agent({`, `sdd-contract-probe`, `Explore` returned no matches — so `sdd-spec` has no existing subagent seam; `sdd-proposal` does (fork lanes §4.0, probe agents §4d, in the command text already in context). Twin copies for other hosts: `.agent/workflows/sdd-spec.md`, `.agents/skills/sdd-spec/` (seen in a worktree listing).

## Citations

- path: `.claude/commands/sdd-spec.md`
  lines: 1
  symbol: `sdd-spec command`
  excerpt: |
    (no matches for: subagent_type | Agent({ | sdd-contract-probe | Explore)

- path: `.claude/commands/sdd-proposal.md`
  lines: 1
  symbol: `sdd-proposal command`
  excerpt: |
    (defines fork research lanes and sdd-contract-probe dispatch — the only existing delegation seam)

## Notes

Expert delegation from `sdd-spec` would be a brand-new section of the command (and its twins), not an extension of an existing hook.
