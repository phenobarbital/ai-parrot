---
id: FW-018
query_id: Q018
type: wiki_query
intent: "Prior SDD art on personas / experts / knowledge tiers"
executed_at: 2026-10-30T16:47:12Z
duration_ms: 400
parent_id: null
depth: 0
---

# FW-018 — No prior SDD doc covers "domain experts" or knowledge tiers; nearest art: FEAT-321 identity brainstorm/spec, `sdd-secondopinion` neutral subagent brief (TASK-1900), HITL escalation tier spec, SDD taxonomy `projects`/`tags` (FEAT-576), and example crews

## Summary

The query for personas/experts/knowledge tiers returned no spec, proposal or brainstorm about domain experts, expert bundles, two-tier knowledge, or governance rule chains — `sdd/proposals/domain-experts.proposal.md` (the source) is the only such document. Adjacent art: `promptbuilder-identity-capability.brainstorm.md` + spec (FEAT-321, persona files), TASK-1900 `sdd-secondopinion` neutral subagent brief (blind review precedent: the reviewer never receives the primary's reasoning), `sdd/specs/hitl-escalation-tier.spec.md` (a "tier" vocabulary already used for HITL escalation — name collision risk with `tier: judgment|balanced|templated`), `sdd/specs/sdd-spec-changes.spec.md` (FEAT-576 `projects`/`tags` frontmatter taxonomy), `.agent/rules/` + `.agent/rules.md` (repo-level agent rule files), and `examples/crew/*.py` orchestrators.

## Citations

- path: `sdd/proposals/promptbuilder-identity-capability.brainstorm.md`
  symbol: `FEAT-321 brainstorm`
  wiki_page_id: file:sdd/proposals/promptbuilder-identity-capability.brainstorm.md
  score: 18.31
  excerpt: |
    (brainstorm behind FW-002; Options A/C/D rejected incl. sectioned single-file identity)

- path: `sdd/tasks/completed/TASK-1900-secondopinion-subagent-brief.md`
  symbol: `sdd-secondopinion neutral subagent brief`
  wiki_page_id: file:sdd/tasks/completed/TASK-1900-secondopinion-subagent-brief.md
  score: 13.71
  excerpt: |
    TASK-1900: `sdd-secondopinion` neutral subagent brief

- path: `sdd/specs/hitl-escalation-tier.spec.md`
  symbol: `HITL escalation tier`
  wiki_page_id: file:sdd/specs/hitl-escalation-tier.spec.md
  score: 14.13
  excerpt: |
    (uses the word "tier" for escalation levels)

- path: `sdd/specs/sdd-spec-changes.spec.md`
  symbol: `FEAT-576 projects/tags frontmatter`
  wiki_page_id: file:sdd/specs/sdd-spec-changes.spec.md
  score: 13.25
  excerpt: |
    Feature Specification: SDD Document Taxonomy — `projects` and `tags` frontmatter

- path: `.agent/rules/`
  symbol: `(6 entries) repo agent rules`
  wiki_page_id: dir:.agent/rules
  score: 17.56
  excerpt: |
    Directory overview of .agent/rules (6 entries)

## Notes

Evidence of absence (checked 2026-10-30 against the local wiki plane): no duplicate spec to fold into. `.claude/agents/sdd-secondopinion.md` is the live precedent for "mutually blind, identity-marked contributions" (see codebase lane Q045).
