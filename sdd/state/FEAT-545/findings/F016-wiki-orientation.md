---
id: F016
query_id: Q001
type: wiki_query
intent: Orient via the knowledge graph: sdd-spec location and Codex adversarial plumbing
executed_at: 2026-09-10T01:00:00Z
duration_ms: 2000
parent_id: null
depth: 0
---

# F016 — Wiki confirms the two subsystems and points at FEAT-375 as the prior Codex-seat feature

## Summary

Q001 ("sdd-spec command scaffold feature specification") ranked `dir:.agent/workflows` (1.00), `file:docs/sdd/WORKFLOW.md` (0.85), `file:sdd/WORKFLOW.md` (0.55), `file:sdd/tasks/completed/TASK-1966-wire-sdd-task-sdd-spec-to-allocator.md` (0.39) and `file:.agent/workflows/sdd-spec.md` (0.02) — the `.claude/commands/` copy is not indexed, only the twin. Q002 ("codex adversarial second opinion reviewer dispatcher") ranked `sym:...code_review.py#CodexAdversarialReviewDispatcher` (1.00), `file:sdd/proposals/codex-cli-agent.proposal.md` (0.68), `file:sdd/specs/codex-cli-agent.spec.md` (0.03) and FEAT-375 state findings — i.e. the Codex seat was introduced by FEAT-375 "codex-cli-agent" and its spec is the design precedent to cite.

## Citations

- path: `.agent/workflows/sdd-spec.md`
  lines: 0
  symbol: wiki page file:.agent/workflows/sdd-spec.md (score 0.02)
- path: `sdd/WORKFLOW.md`
  lines: 0
  symbol: wiki page file:sdd/WORKFLOW.md (score 0.55)
- path: `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py`
  lines: 0
  symbol: wiki page sym:...#CodexAdversarialReviewDispatcher (score 1.00) — "Read-only adversarial second-opinion reviewer (FEAT-375 G1)"
- path: `sdd/specs/codex-cli-agent.spec.md`
  lines: 0
  symbol: wiki page (score 0.03) — FEAT-375 spec, design precedent
- path: `sdd/proposals/codex-cli-agent.proposal.md`
  lines: 0
  symbol: wiki page (score 0.68)
- path: `sdd/state/FEAT-375/findings/F002-codex-review-dispatcher.md`
  lines: 0
  symbol: wiki page (score 0.67) — "Codex code review exists but is WRITE-ENABLED, not adversarial/advisory"

## Notes

Wiki reports 624 stale sources; results were used for orientation only and every path above was then read directly (F001–F015).
