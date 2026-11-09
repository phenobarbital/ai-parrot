---
id: F012
query_id: Q019
type: git_log
intent: "Recent changes to the CrewDefinition model."
executed_at: 2026-11-09T17:16:00Z
duration_ms: 700
parent_id: null
depth: 0
merged_from: [FG-002]
---

# F012 — Recent history of the CrewDefinition model

## Summary

Six commits in 120 days on `crew_definition.py`, plus the hidden 413d4067a8
(68 lines, tenant hardening). The model keeps growing fields (ToolNode /
special nodes 2026-07-14, infographic theme 2026-09-17) and became strict:
0e221d75c8 (2026-08-16) validates the definition instead of failing silently,
which is what made the read-side compat in CrewRedis necessary. A stored
definition is therefore a moving schema — a Postgres table should keep the
full definition in a jsonb column rather than one column per field.

## Citations

- sha: `47156b3554`
  date: 2026-07-14
  author: Claude
  message: "feat(crew): deterministic ToolNode for AgentCrew + special-nodes catalog API"

- sha: `6131cec944`
  date: 2026-07-14
  author: Jesus Lara
  message: "fixing the infographic call during crew execution"

- sha: `32e17d0e3d`
  date: 2026-07-19
  author: Claude
  message: "feat(crew): execution wiki — record intermediate results + tool calls, searchable via LLM Wiki plane"

- sha: `0e221d75c8`
  date: 2026-08-16
  author: Claude
  message: "feat(crew): validate CrewDefinition instead of failing silently"

- sha: `3f6a5d3ffa`
  date: 2026-08-20
  author: Jesus
  message: "fix(flows): address code-review findings on workflow authoring"
  excerpt: |
    `CrewDefinition.validate_flow_relations` rejected relations written
    against an `agent_id` ... now accepted and normalised to the canonical display name

- sha: `03e9a7cf51`
  date: 2026-09-17
  author: Jesus Lara
  message: "feat(crew): configurable infographic theme on CrewDefinition/AgentCrew"

- sha: `413d4067a8`
  date: 2026-08-24
  author: Jesus Lara
  message: "fix(saas-auth-hardening): close cross-tenant gaps found in code review"
  files: `packages/ai-parrot/src/parrot/models/crew_definition.py` (68 lines)

## Notes

- [cross-lane: type=read, intent=read crew_definition.py for identity fields (crew_id, name, tenant) and the extra="forbid" config added by 0e221d75c8]
